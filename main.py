"""
AI-Powered Job Hunter - Main Orchestrator v3.0

Main script that ties all modules together. Upgraded to run as a fully asynchronous,
non-blocking service that integrates directly with the Telegram AgentBridge.
"""

import os
import sys
import time
import json
import csv
import asyncio
import datetime
import concurrent.futures
from dotenv import load_dotenv

# Reconfigure stdout/stderr for robust real-time log tailing
sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')

# Dynamic path resolution to import the Telegram AgentBridge
telegram_path = r"c:\Users\alex0\Desktop\agent_phone_bot\telegram_agent_controller"
if telegram_path not in sys.path:
    sys.path.append(telegram_path)

try:
    from bot_controller import send_notification, send_document, agent_bridge
    logger_prefix = "TelegramBridge"
except ImportError:
    # Fallback mock implementations for standalone out-of-box operation
    send_notification = None
    send_document = None
    agent_bridge = None
    logger_prefix = "ConsoleFallback"

from scrapers.engine import (
    ScrapingEngine,
    LinkedInScraper,
    IndeedScraper,
    JobMasterScraper,
    DrushimScraper,
    AllJobsScraper,
    NishaScraper
)
from ai import brain
from db import database
from scrapers import email_tracker
from geo_filter import pre_filter_job

# Global list to hold matches found this scan cycle
unnotified_matches = []


def run_evaluations(found_jobs, process_job_fn):
    """
    Helper function to run job evaluations concurrently within a thread pool
    without blocking the primary async event loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        executor.map(process_job_fn, found_jobs)


async def frequent_job_hunt_cycle():
    global unnotified_matches
    print("--- Starting Asynchronous Job Hunting Cycle ---")
    
    # Load environment configurations
    load_dotenv()
    
    print("Initializing Database...")
    database.init_db()
    
    print("Checking emails for progress updates...")
    email_tracker.check_emails()
    
    # Notify launch state
    if send_notification:
        await send_notification("🚀 **AI Job Hunter sweep has started!** Launching headed browser scrapers...")
    
    print("Starting Job Scraper (Headed Playwright Browser)...")
    # Instantiating scraping engine directly to run asynchronously without loop collisions
    engine = ScrapingEngine(max_concurrent=4, cache_ttl=3600, enable_caching=True, cb_failure_threshold=5)
    scrapers = [
        LinkedInScraper(),
        IndeedScraper(),
        JobMasterScraper(),
        DrushimScraper(),
        AllJobsScraper(),
        NishaScraper(),
    ]
    
    # Search queries
    search_queries = [
        "Student Developer", "Python Student", "Software Engineer Student",
        "Data Engineer Junior", "Junior Software Engineer", "Junior Python Developer",
        "Junior Data Analyst", "בוגר מדעי המחשב", "משרת סטודנט",
    ]
    
    try:
        found_jobs, results = await engine.run_async(scrapers, search_queries)
        total_scanned = len(found_jobs) if found_jobs else 0
    except Exception as e:
        print(f"Critical error during scraper launch: {e}")
        if send_notification:
            await send_notification(f"❌ **Scraping phase crashed:**\n`{e}`")
        return

    if not found_jobs:
        print("No jobs found during scraping.")
        print("Running deduplication pass...")
        dupes_removed = database.deduplicate_jobs()
        
        print("Cleaning up low scoring jobs...")
        database.cleanup_low_scoring_jobs()
        
        print("Running geo-filter pass...")
        import geo_filter
        geo_filtered = geo_filter.run_geo_filter()
        
        to_apply_jobs = database.get_jobs_by_stage('To Apply')
        total_to_apply = len(to_apply_jobs)
        
        # Dispatch Telegram notification summary
        summary_msg = (
            "📊 **AI Job Hunter Scan Summary**\n"
            "Status: `0 new matches found this cycle.`\n\n"
            f"🧹 **Duplicates Cleaned:** `{dupes_removed}`\n"
            f"📍 **Geo-Filtered Out:** `{geo_filtered}`\n"
            f"📂 **Total Backlog to Apply:** `{total_to_apply}`"
        )
        if send_notification:
            await send_notification(summary_msg)
        else:
            print(summary_msg)
            
        with open("last_update.txt", "w") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("--- Frequent cycle completed ---")
        return

    print(f"Found {total_scanned} jobs. Analyzing...")
    if send_notification:
        await send_notification(f"🔍 **Scraping complete.** Scanned `{total_scanned}` jobs. Starting AI target evaluations...")

    def process_job(job):
        try:
            url = job.get('url')
            if database.is_job_processed(url, title=job.get('title'), company=job.get('company')):
                print(f"Skipping already processed job: {job.get('title')} at {job.get('company')}")
                return
                
            print(f"Evaluating: {job.get('title')} at {job.get('company')}...")
            
            # Programmatic Pre-Filter Check
            is_rejected, reason = pre_filter_job(job)
            if is_rejected:
                print(f"  [PRE-FILTER REJECTED]: {reason}. Skipping AI call.")
                evaluation = {
                    "is_relevant": False,
                    "match_score": 0,
                    "summary": f"Rejected by pre-filter: {reason}.",
                    "location": job.get('location', 'Not specified'),
                    "key_features": "N/A",
                    "important_qualifications": "N/A"
                }
                database.add_job(
                    title=job.get('title'),
                    company=job.get('company'),
                    url=url,
                    location=job.get('location', 'Not specified'),
                    ai_summary=json.dumps(evaluation),
                    stage='Irrelevant'
                )
                return

            evaluation = brain.evaluate_job(job)
            score = int(evaluation.get('match_score', 0))
            is_relevant = evaluation.get('is_relevant', False) and score >= 70
            
            if is_relevant:
                print(f"Match found! Score: {score}")
                database.add_job(
                    title=job.get('title'),
                    company=job.get('company'),
                    url=url,
                    location=job.get('location', 'Not specified'),
                    ai_summary=json.dumps(evaluation),
                    stage='To Apply'
                )
                unnotified_matches.append({
                    "job": job,
                    "evaluation": evaluation
                })
            else:
                print(f"Not a good fit. Skipping.")
                database.add_job(
                    title=job.get('title'),
                    company=job.get('company'),
                    url=url,
                    location=job.get('location', 'Not specified'),
                    ai_summary=json.dumps(evaluation),
                    stage='Irrelevant'
                )
        except Exception as e:
            print(f"Error processing job '{job.get('title')}' at '{job.get('company')}': {e}")

    # Run blocking Gemini AI evaluations in a separate thread pool to keep bot responsive
    print(f"Evaluating {total_scanned} jobs concurrently...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: run_evaluations(found_jobs, process_job))

    print("Running deduplication pass...")
    dupes_removed = database.deduplicate_jobs()

    print("Cleaning up low scoring jobs...")
    database.cleanup_low_scoring_jobs()

    print("Running geo-filter pass...")
    import geo_filter
    geo_filtered = geo_filter.run_geo_filter()

    to_apply_jobs = database.get_jobs_by_stage('To Apply')
    total_to_apply = len(to_apply_jobs)

    new_match_count = len(unnotified_matches)
    print(f"AI filtration completed. {new_match_count} suitable matches identified.")

    # Two-way Interactive Callback integration:
    if new_match_count > 0 and agent_bridge is not None:
        # Prompt allowed user for report generation approval
        prompt = f"🎯 **Job Hunter Sweep Complete!**\n\nFound `{new_match_count}` matching jobs. Approve generating the CSV report and proceeding?"
        print("Awaiting user approval via Telegram...")
        approved = await agent_bridge.request_user_approval(prompt)
        
        if approved:
            print("User approved. Generating CSV listing...")
            await send_notification("✅ **Approval received!** Generating and packaging CSV listing report...")
            
            # Generate the actual CSV report of the job listings
            csv_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matching_job_listings.csv")
            try:
                with open(csv_file_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                    writer = csv.writer(csvfile)
                    # Headers
                    writer.writerow(["Job Title", "Company", "Location", "AI Match Score", "URL"])
                    for m in unnotified_matches:
                        j = m["job"]
                        ev = m["evaluation"]
                        writer.writerow([
                            j.get("title", ""),
                            j.get("company", ""),
                            j.get("location", ""),
                            ev.get("match_score", 0),
                            j.get("url", "")
                        ])
                
                # Deliver generated artifact directly to user
                await send_document(
                    csv_file_path,
                    caption=f"📊 **Matching Job listings Report**\n*Found {new_match_count} matching openings during this sweep.*"
                )
            except Exception as ex:
                print(f"Error packaging CSV document: {ex}")
                await send_notification(f"❌ **Failed to generate CSV artifact:**\n`{ex}`")
            finally:
                if os.path.exists(csv_file_path):
                    os.remove(csv_file_path)
        else:
            print("User rejected CSV export.")
            await send_notification("❌ **CSV Generation Cancelled.** Export cancelled by user request.")

    elif new_match_count > 0:
        # Fallback notification if bridge is not loaded
        print(f"Telegram path not resolved. Dispatching fallback log notification.")
        print(f"Found matches: {new_match_count}")
        
    # Dispatch general scan summary notification
    summary_msg = (
        "📊 **AI Job Hunter Sweep Report**\n\n"
        f"🔍 **Jobs Scanned:** `{total_scanned}`\n"
        f"✨ **New Matches Found:** `{new_match_count}`\n"
        f"🧹 **Duplicates Cleaned:** `{dupes_removed}`\n"
        f"📍 **Geo-Filtered Out:** `{geo_filtered}`\n"
        f"📂 **Total 'To Apply' Backlog:** `{total_to_apply}`"
    )
    
    if send_notification:
        await send_notification(summary_msg)
    else:
        print(summary_msg)

    unnotified_matches.clear()

    with open("last_update.txt", "w") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("--- Asynchronous cycle completed ---")


def set_low_priority():
    """Sets the process priority to BELOW NORMAL on Windows to reduce impact on system performance."""
    if sys.platform == 'win32':
        try:
            import ctypes
            # 0x00004000 is BELOW_NORMAL_PRIORITY_CLASS
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
            print("Process priority set to BELOW NORMAL to prevent system lag.")
        except Exception as e:
            print(f"Could not adjust process priority: {e}")


def main():
    set_low_priority()
    
    if "--single" in sys.argv:
        print("Running in SINGLE-SHOT mode (Zero-Footprint background run)...")
        asyncio.run(frequent_job_hunt_cycle())
        print("Single-shot run completed. Exiting and releasing all memory!")
        sys.exit(0)
        
    print("Job Finder is running.")
    print("Scraping and checking emails every 1 hour.")
    
    # Asynchronous loop execution
    async def async_main_loop():
        # Execute first cycle immediately
        await frequent_job_hunt_cycle()
        while True:
            # Check every 1 hour (3600 seconds)
            await asyncio.sleep(3600)
            await frequent_job_hunt_cycle()
            
    try:
        asyncio.run(async_main_loop())
    except KeyboardInterrupt:
        print("System interrupted by user. Exiting cleanly.")


if __name__ == "__main__":
    main()
