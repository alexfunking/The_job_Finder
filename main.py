"""
Phase 6: Orchestrator
Main script that ties all modules together.
"""
import os
import time
import json
import schedule
from dotenv import load_dotenv
import scraper
import brain
import database
import notifier
import email_tracker

# Global list to hold matches found throughout the day
unnotified_matches = []

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
    found_jobs = scraper.scrape_jobs()
    
    if not found_jobs:
        print("No jobs found during scraping.")
        import datetime
        with open("last_update.txt", "w") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("--- Frequent cycle completed ---")
        return

    print(f"Found {len(found_jobs)} jobs. Analyzing...")
    
    for job in found_jobs:
        url = job.get('url')
        
        # De-duplication check
        if database.is_job_processed(url):
            print(f"Skipping already processed job: {job.get('title')} at {job.get('company')}")
            continue
            
        print(f"Evaluating: {job.get('title')}...")
        evaluation = brain.evaluate_job(job)
        time.sleep(0.5) # Brief pause to respect API throughput limits
        
        # Enforce threshold of 70% match score or is_relevant flag
        is_relevant = evaluation.get('is_relevant') or int(evaluation.get('match_score', 0)) >= 70
        if is_relevant:
            print(f"Match found! Score: {evaluation.get('match_score')}")
            # Save to DB
            database.add_job(
                title=job.get('title'),
                company=job.get('company'),
                url=url,
                ai_summary=json.dumps(evaluation)
            )
            
            # Add to matches list for daily batch notification
            unnotified_matches.append({
                "job": job,
                "evaluation": evaluation
            })
        else:
            print(f"Not a good fit. Skipping.")
            # Mark it as processed by saving it with score 0/irrelevant
            database.add_job(
                title=job.get('title'),
                company=job.get('company'),
                url=url,
                ai_summary=json.dumps(evaluation)
            )

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

def main():
    print("Job Finder is running.")
    print("Scraping and checking emails every 1 hour.")
    print("Sending WhatsApp summary daily at 10:00 AM.")
    
    # Schedule the frequent cycle to run every 1 hour
    schedule.every(1).hours.do(frequent_job_hunt_cycle)
    
    # Schedule the notification to run every day at 10:00 AM
    schedule.every().day.at("10:00").do(send_daily_summary)
    
    # Run the initial cycle immediately so the dashboard updates right away
    frequent_job_hunt_cycle()

    while True:
        schedule.run_pending()
        time.sleep(60) # Wait one minute between checks

if __name__ == "__main__":
    main()
