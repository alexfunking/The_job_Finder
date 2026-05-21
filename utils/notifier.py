"""
Phase 5: Notification Module
Sends WhatsApp notifications using the Twilio API.
"""
import os
from twilio.rest import Client

def send_whatsapp_notification(job_details: dict, ai_evaluation: dict):
    """
    Sends a WhatsApp message with job details and a direct application link.
    """
    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_TOKEN')
    from_whatsapp_number = os.getenv('TWILIO_FROM_PHONE')
    to_whatsapp_number = os.getenv('TARGET_PHONE_NUMBER')
    
    if not all([account_sid, auth_token, from_whatsapp_number, to_whatsapp_number]):
        print("Twilio credentials missing. Skipping notification.")
        return

    client = Client(account_sid, auth_token)

    location = ai_evaluation.get('location', 'Not specified')
    features = ai_evaluation.get('key_features', 'N/A')

    message_body = (
        f"🤖 *New Job Match!*\n\n"
        f"*{job_details.get('title')}* at {job_details.get('company')}\n"
        f"📍 {location} | 🎯 Score: {ai_evaluation.get('match_score')}/100\n"
        f"✨ {features}\n\n"
        f"Summary: {ai_evaluation.get('summary')}\n\n"
        f"Apply here: {job_details.get('url')}"
    )

    dashboard_link = ""
    url_path = os.path.join(os.path.dirname(__file__), "..", "public_url.txt")
    if os.path.exists(url_path):
        try:
            with open(url_path, "r") as f:
                dashboard_link = f.read().strip()
        except:
            pass
            
    if dashboard_link:
        message_body += f"\n\n📱 Open Dashboard: {dashboard_link}"

    try:
        message = client.messages.create(
            body=message_body,
            from_=from_whatsapp_number,
            to=to_whatsapp_number
        )
        print(f"WhatsApp message sent! SID: {message.sid}")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")

def send_scan_summary(new_matches: list, total_to_apply: int, duplicates_removed: int = 0, total_scanned: int = 0, geo_filtered: int = 0):
    """
    Sends a WhatsApp summary message after every scan cycle finishes.
    Shows: how many new jobs found this scan, score breakdown, and top 3 links.
    
    new_matches: list of {'job': {...}, 'evaluation': {...}} found THIS scan
    total_to_apply: total count of 'To Apply' jobs in the DB right now
    duplicates_removed: how many dupes were cleaned this cycle
    total_scanned: total number of jobs scraped from the web
    geo_filtered: number of overseas jobs filtered out
    """
    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_TOKEN')
    from_whatsapp_number = os.getenv('TWILIO_FROM_PHONE')
    to_whatsapp_number = os.getenv('TARGET_PHONE_NUMBER')

    if not all([account_sid, auth_token, from_whatsapp_number, to_whatsapp_number]):
        print("Twilio credentials missing. Skipping scan summary notification.")
        return

    client = Client(account_sid, auth_token)

    # Score breakdown (only score >= 70 are kept in new_matches)
    tier_95 = [m for m in new_matches if int(m['evaluation'].get('match_score', 0)) >= 95]
    tier_85 = [m for m in new_matches if 85 <= int(m['evaluation'].get('match_score', 0)) < 95]
    tier_70 = [m for m in new_matches if 70 <= int(m['evaluation'].get('match_score', 0)) < 85]

    # Build premium WhatsApp message
    msg = f"🔍 *Job Search Scan Completed!* 🤖\n\n"
    msg += f"📊 *Scan Statistics:*\n"
    msg += f"• 🌐 Total Scanned on Web: {total_scanned}\n"
    msg += f"• 🎯 New Matches (Score ≥ 70): {len(new_matches)}\n"
    msg += f"• 🧹 Duplicates Cleaned: {duplicates_removed}\n"
    msg += f"• 🗺️ Overseas Jobs Filtered: {geo_filtered}\n"
    msg += f"• 💼 Total 'To Apply' in Dashboard: {total_to_apply}\n\n"

    msg += f"🌟 *Score Breakdown (New Matches):*\n"
    msg += f"• 🏆 95-100 (Student / Internship): {len(tier_95)}\n"
    msg += f"• 🥇 85-94 (No Experience Required): {len(tier_85)}\n"
    msg += f"• ⭐️ 70-84 (Junior / 1-2 Yrs Exp): {len(tier_70)}\n"

    # Top 3 new matches
    top = sorted(new_matches, key=lambda m: int(m['evaluation'].get('match_score', 0)), reverse=True)[:3]
    if top:
        msg += f"\n🚀 *Top Picks From This Scan:*\n"
        for i, match in enumerate(top, 1):
            job = match['job']
            ev = match['evaluation']
            score = ev.get('match_score', 0)
            location = ev.get('location', 'N/A')
            msg += f"  {i}. *{job.get('title')}* @ {job.get('company')}\n"
            msg += f"     📍 Location: {location} | 🎯 Score: {score}/100\n"
            if ev.get('key_features'):
                msg += f"     ✨ {ev.get('key_features')}\n"
            msg += f"     🔗 {job.get('url')}\n"

    # Dashboard link
    dashboard_link = ""
    url_path = os.path.join(os.path.dirname(__file__), "..", "public_url.txt")
    if os.path.exists(url_path):
        try:
            with open(url_path, "r") as f:
                dashboard_link = f.read().strip()
        except Exception:
            pass

    if dashboard_link:
        msg += f"\n📱 *View Kanban Dashboard:*\n{dashboard_link}"

    # Truncate if needed (Twilio ~1600 char limit)
    if len(msg) > 1550:
        msg = msg[:1550] + "\n...(truncated)"

    try:
        message = client.messages.create(
            body=msg.strip(),
            from_=from_whatsapp_number,
            to=to_whatsapp_number
        )
        print(f"Scan summary WhatsApp sent! SID: {message.sid}")
    except Exception as e:
        print(f"Failed to send scan summary: {e}")


def send_batch_whatsapp_notification(matches: list):
    """Legacy function kept for compatibility. Calls send_scan_summary internally."""
    send_scan_summary(new_matches=matches, total_to_apply=len(matches))
