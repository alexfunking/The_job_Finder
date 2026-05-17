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

    try:
        message = client.messages.create(
            body=message_body,
            from_=from_whatsapp_number,
            to=to_whatsapp_number
        )
        print(f"WhatsApp message sent! SID: {message.sid}")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")

def send_batch_whatsapp_notification(matches: list):
    """
    Sends a single WhatsApp message summarizing multiple job matches.
    """
    if not matches:
        return

    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_TOKEN')
    from_whatsapp_number = os.getenv('TWILIO_FROM_PHONE')
    to_whatsapp_number = os.getenv('TARGET_PHONE_NUMBER')
    
    if not all([account_sid, auth_token, from_whatsapp_number, to_whatsapp_number]):
        print("Twilio credentials missing. Skipping batch notification.")
        return

    client = Client(account_sid, auth_token)

    # Construct batch message
    message_body = f"🤖 *Daily Job Matches ({len(matches)})*\n\n"
    
    for i, match in enumerate(matches, 1):
        job = match['job']
        eval_data = match['evaluation']
        location = eval_data.get('location', 'Not specified')
        features = eval_data.get('key_features', '')

        message_body += (
            f"*{i}. {job.get('title')}* @ {job.get('company')}\n"
            f"📍 {location} | 🎯 Score: {eval_data.get('match_score')}/100\n"
            f"✨ {features}\n"
            f"Link: {job.get('url')}\n\n"
        )

    # Twilio limits WhatsApp messages to 1600 characters usually,
    # but let's just send it. If it's too long, we might need to split it.
    if len(message_body) > 1500:
        message_body = message_body[:1500] + "\n... (Message truncated)"

    try:
        message = client.messages.create(
            body=message_body.strip(),
            from_=from_whatsapp_number,
            to=to_whatsapp_number
        )
        print(f"Batch WhatsApp message sent! SID: {message.sid}")
    except Exception as e:
        print(f"Failed to send batch WhatsApp message: {e}")
