import sqlite3
import json
import time
import sys
import os

# Add current directory to path so we can import packages
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from db import database
from ai import brain
from dotenv import load_dotenv

sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def reevaluate_all_jobs():
    print("Connecting to database...")
    conn = sqlite3.connect("jobs.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Fetch jobs that are in "To Apply" or "Irrelevant" stages to allow rescuing under relaxed rules
    cursor.execute("SELECT * FROM jobs WHERE stage IN ('To Apply', 'Irrelevant')")
    jobs = cursor.fetchall()
    
    if not jobs:
        print("No jobs in 'To Apply' stage to re-evaluate.")
        return

    print(f"Found {len(jobs)} jobs in 'To Apply' to re-evaluate using new rules.\n")
    
    for row in jobs:
        job_id = row['id']
        title = row['title']
        company = row['company']
        url = row['url']
        ai_summary_str = row['ai_summary']
        
        old_description = "Re-evaluating based on updated strict geographical and student rules."
        old_location = "Not specified"
        try:
            if ai_summary_str:
                old_summary_data = json.loads(ai_summary_str)
                old_location = old_summary_data.get('location', 'Not specified')
                old_summary = old_summary_data.get('summary', '')
                old_qualifications = old_summary_data.get('important_qualifications', '')
                old_description = f"Previous Evaluation Info:\nLocation: {old_location}\nSummary: {old_summary}\nQualifications: {old_qualifications}"
        except Exception:
            pass

        print(f"Re-evaluating: {title} @ {company}")
        job_dict = {
            "title": title,
            "company": company,
            "url": url,
            "location": old_location,
            "description": old_description
        }
        
        try:
            from geo_filter import pre_filter_job
            is_rejected, reason = pre_filter_job(job_dict)
            if is_rejected:
                print(f"  -> [PRE-FILTER REJECTED]: {reason}. Skipping AI.")
                evaluation = {
                    "is_relevant": False,
                    "match_score": 0,
                    "summary": f"Rejected by pre-filter: {reason}.",
                    "location": old_location,
                    "key_features": "N/A",
                    "important_qualifications": "N/A"
                }
                update_cursor = conn.cursor()
                update_cursor.execute("""
                    UPDATE jobs 
                    SET ai_summary = ?, stage = 'Irrelevant'
                    WHERE id = ?
                """, (json.dumps(evaluation), job_id))
                conn.commit()
                print(f"  -> New Score: 0/100 | Moved to: Irrelevant\n")
                continue

            # Re-evaluate with AI
            evaluation = brain.evaluate_job(job_dict)
            time.sleep(0.5) # Prevent rate limits
            
            new_score = int(evaluation.get('match_score', 0))
            is_relevant = evaluation.get('is_relevant', False) and new_score >= 70
            
            new_stage = 'To Apply' if is_relevant else 'Irrelevant'
            
            # Update DB
            update_cursor = conn.cursor()
            update_cursor.execute("""
                UPDATE jobs 
                SET ai_summary = ?, stage = ?
                WHERE id = ?
            """, (json.dumps(evaluation), new_stage, job_id))
            conn.commit()
            
            print(f"  -> New Score: {new_score}/100 | Moved to: {new_stage}\n")
            
        except Exception as e:
            print(f"  -> Error evaluating job {job_id}: {e}\n")
            
    conn.close()
    print("Re-evaluation complete!")

if __name__ == "__main__":
    reevaluate_all_jobs()
