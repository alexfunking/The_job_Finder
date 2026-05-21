"""
Phase 6: Orchestrator
Main script that ties all modules together.
"""
import os
import time
import json
import sys
import schedule
from dotenv import load_dotenv

sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')

from scrapers import engine as scraper
from ai import brain
from db import database
from utils import notifier
from scrapers import email_tracker

# Global list to hold matches found this scan cycle
unnotified_matches = []

from geo_filter import pre_filter_job
import concurrent.futures

def frequent_job_hunt_cycle():
    global unnotified_matches
    print("--- Starting Frequent Job Hunting Cycle ---")
    # Load environment variables from .env file
    load_dotenv()
    
    print("Initializing Database...")
    database.init_db()
    
    print("Checking emails for progress updates...")
    email_tracker.check_emails()
    
    print("Starting Job Scraper...")
    # Get potentially new jobs
    found_jobs = scraper.run_scrape_jobs()
    total_scanned = len(found_jobs) if found_jobs else 0
    
    if not found_jobs:
        print("No jobs found during scraping.")
        # --- Deduplication pass ---
        print("Running deduplication pass...")
        dupes_removed = database.deduplicate_jobs()
        
        # --- Cleanup low scoring jobs ---
        print("Cleaning up low scoring jobs...")
        database.cleanup_low_scoring_jobs()
        
        # --- Geo-filter pass ---
        print("Running geo-filter pass...")
        import geo_filter
        geo_filtered = geo_filter.run_geo_filter()
        
        # --- Count current To Apply total ---
        to_apply_jobs = database.get_jobs_by_stage('To Apply')
        total_to_apply = len(to_apply_jobs)
        
        # --- Send WhatsApp scan summary ---
        print("Sending scan summary: 0 new matches found this cycle.")
        notifier.send_scan_summary(
            new_matches=[],
            total_to_apply=total_to_apply,
            duplicates_removed=dupes_removed,
            total_scanned=0,
            geo_filtered=geo_filtered
        )
        
        import datetime
        with open("last_update.txt", "w") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("--- Frequent cycle completed ---")
        return

    print(f"Found {total_scanned} jobs. Analyzing...")
    
    def process_job(job):
        url = job.get('url')
        
        # De-duplication check — by URL AND by title+company
        if database.is_job_processed(url, title=job.get('title'), company=job.get('company')):
            print(f"Skipping already processed job: {job.get('title')} at {job.get('company')}")
            return
            
        print(f"Evaluating: {job.get('title')} at {job.get('company')}...")
        
        # 1. Programmatic Pre-Filter Check
        is_rejected, reason = pre_filter_job(job)
        if is_rejected:
            print(f"  [PRE-FILTER REJECTED]: {reason}. Skipping AI call.")
            # Save it with stage='Irrelevant' and match_score=0
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
        
        # Enforce threshold of 70% match score AND is_relevant flag from AI
        score = int(evaluation.get('match_score', 0))
        is_relevant = evaluation.get('is_relevant', False) and score >= 70
        if is_relevant:
            print(f"Match found! Score: {score}")
            # Save to DB
            database.add_job(
                title=job.get('title'),
                company=job.get('company'),
                url=url,
                location=job.get('location', 'Not specified'),
                ai_summary=json.dumps(evaluation),
                stage='To Apply'
            )
            
            # Add to matches list for daily batch notification (thread-safe due to GIL)
            unnotified_matches.append({
                "job": job,
                "evaluation": evaluation
            })
        else:
            print(f"Not a good fit. Skipping.")
            # Mark it as processed by saving it with score 0/irrelevant and stage='Irrelevant'
            database.add_job(
                title=job.get('title'),
                company=job.get('company'),
                url=url,
                location=job.get('location', 'Not specified'),
                ai_summary=json.dumps(evaluation),
                stage='Irrelevant'
            )

    print(f"Found {total_scanned} jobs. Analyzing concurrently...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_job, found_jobs)

    # --- Deduplication pass ---
    print("Running deduplication pass...")
    dupes_removed = database.deduplicate_jobs()
    if dupes_removed > 0:
        print(f"Removed {dupes_removed} duplicate job(s) from the database.")

    # --- Cleanup low scoring jobs ---
    print("Cleaning up low scoring jobs...")
    database.cleanup_low_scoring_jobs()

    # --- Geo-filter pass ---
    print("Running geo-filter pass...")
    import geo_filter
    geo_filtered = geo_filter.run_geo_filter()

    # --- Count current To Apply total ---
    to_apply_jobs = database.get_jobs_by_stage('To Apply')
    total_to_apply = len(to_apply_jobs)

    # --- Send WhatsApp scan summary ---
    print(f"Sending scan summary: {len(unnotified_matches)} new match(es) found this cycle.")
    notifier.send_scan_summary(
        new_matches=unnotified_matches,
        total_to_apply=total_to_apply,
        duplicates_removed=dupes_removed,
        total_scanned=total_scanned,
        geo_filtered=geo_filtered
    )
    unnotified_matches.clear()

    import datetime
    with open("last_update.txt", "w") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("--- Frequent cycle completed ---")

def send_daily_summary():
    global unnotified_matches
    print("--- Sending Daily WhatsApp Summary ---")
    if unnotified_matches:
        print(f"Sending batch notification for {len(unnotified_matches)} new matches...")
        notifier.send_batch_whatsapp_notification(unnotified_matches)
        unnotified_matches.clear() # Reset the list after sending
    else:
        print("No new suitable matches found today. No notification sent.")
    print("--- Daily summary completed ---")

def set_low_priority():
    """Sets the process priority to BELOW NORMAL on Windows to reduce impact on system performance."""
    import sys
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
    import sys
    
    if "--single" in sys.argv:
        print("Running in SINGLE-SHOT mode (Zero-Footprint background run)...")
        frequent_job_hunt_cycle()
        print("Single-shot run completed. Exiting and releasing all memory!")
        sys.exit(0)
        
    print("Job Finder is running.")
    print("Scraping and checking emails every 1 hour.")
    print("Sending WhatsApp scan summary after every cycle.")
    
    # Schedule the frequent cycle to run every 1 hour
    schedule.every(1).hours.do(frequent_job_hunt_cycle)
    
    # Run the initial cycle immediately so the dashboard updates right away
    frequent_job_hunt_cycle()

    while True:
        schedule.run_pending()
        time.sleep(60) # Wait one minute between checks

if __name__ == "__main__":
    main()
