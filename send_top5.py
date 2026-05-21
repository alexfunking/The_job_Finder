"""
Fetches the top 5 'To Apply' jobs by match_score and sends a WhatsApp summary.
"""
import sqlite3
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from utils import notifier

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")

def get_top_jobs(limit=5):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE stage = 'To Apply'")
    rows = cursor.fetchall()
    conn.close()

    scored = []
    for row in rows:
        score = 0
        eval_data = {}
        try:
            if row['ai_summary']:
                eval_data = json.loads(row['ai_summary'])
                score = int(eval_data.get('match_score', 0))
        except Exception:
            pass
        scored.append({
            "job": dict(row),
            "evaluation": eval_data,
            "score": score
        })

    # Sort by score descending, deduplicate by URL
    seen_urls = set()
    unique = []
    for item in sorted(scored, key=lambda x: x['score'], reverse=True):
        url = item['job'].get('url', '')
        if url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    return unique[:limit]

def build_message(top_jobs):
    dashboard_link = ""
    url_path = os.path.join(os.path.dirname(__file__), "public_url.txt")
    if os.path.exists(url_path):
        try:
            with open(url_path, "r") as f:
                dashboard_link = f.read().strip()
        except Exception:
            pass

    msg = f"*Top {len(top_jobs)} Job Matches*\n\n"
    for i, item in enumerate(top_jobs, 1):
        job = item['job']
        ev = item['evaluation']
        score = item['score']
        location = ev.get('location', 'Not specified')
        summary = ev.get('summary', '')
        features = ev.get('key_features', '')
        url = job.get('url', '')
        title = job.get('title', 'Unknown')
        company = job.get('company', 'Unknown')

        msg += f"*{i}. {title}*\n"
        msg += f"   @ {company}\n"
        msg += f"   Score: {score}/100 | {location}\n"
        if summary:
            msg += f"   {summary}\n"
        if features:
            msg += f"   {features}\n"
        msg += f"   Apply: {url}\n\n"

    if dashboard_link:
        msg += f"Dashboard: {dashboard_link}"

    return msg.strip()

def main():
    print("Fetching top 5 jobs from DB...")
    top_jobs = get_top_jobs(5)

    if not top_jobs:
        print("No jobs found in 'To Apply'.")
        return

    message = build_message(top_jobs)

    print("\n=== WhatsApp Message Preview ===")
    print(message)
    print("================================\n")

    # Send via Twilio
    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_TOKEN')
    from_number = os.getenv('TWILIO_FROM_PHONE')
    to_number = os.getenv('TARGET_PHONE_NUMBER')

    if not all([account_sid, auth_token, from_number, to_number]):
        print("Twilio credentials missing — message printed above but NOT sent.")
        return

    from twilio.rest import Client
    client = Client(account_sid, auth_token)

    # Twilio WhatsApp has a ~1600 char limit, truncate if needed
    if len(message) > 1550:
        message = message[:1550] + "\n...(truncated)"

    try:
        msg_obj = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"WhatsApp message sent! SID: {msg_obj.sid}")
    except Exception as e:
        print(f"Failed to send: {e}")

if __name__ == "__main__":
    main()
