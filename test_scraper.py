import sys
import main
import email_tracker
import database
import scraper
import brain
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("Starting scraper and brain test run...")
try:
    print("Initializing Database...")
    database.init_db()
    
    print("Starting Job Scraper...")
    found_jobs = scraper.scrape_jobs(["Junior Python Developer"])
    print(f"Found {len(found_jobs)} jobs.")
    
    if found_jobs:
        job = found_jobs[0]
        print(f"Evaluating: {job.get('title')} at {job.get('company')}...")
        evaluation = brain.evaluate_job(job)
        print("Evaluation:", evaluation)
        
except Exception as e:
    print(f"Exception caught: {e}")
print("Test run completed.")
