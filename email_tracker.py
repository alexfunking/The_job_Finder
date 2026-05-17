import os
import imaplib
import email
from email.header import decode_header
import json
import google.generativeai as genai
import database
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_companies():
    """Retrieve all companies from jobs currently 'To Apply' or 'In Process'."""
    jobs_to_apply = database.get_jobs_by_stage("To Apply")
    jobs_in_process = database.get_jobs_by_stage("In Process")
    all_active = jobs_to_apply + jobs_in_process
    
    companies = {}
    for job in all_active:
        comp = job['company'].lower().strip()
        if comp not in companies:
            companies[comp] = []
        companies[comp].append(job)
    return companies

def setup_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-2.5-flash')

def classify_email(model, email_subject, email_body, company_name):
    prompt = f"""
    You are an AI assistant tracking job application progress.
    The user applied to a company named "{company_name}".
    Here is an email received from them:
    
    Subject: {email_subject}
    Body: {email_body}
    
    Classify the email based on its intent. 
    Is it a rejection, an invitation for an HR screen, an invitation for a tech interview, a home assignment, an offer, or just an automated "We received your application" message?
    
    Return your response strictly as a JSON object with the following schema:
    {{
        "is_relevant_update": true/false (true only if it's an actual update, false if it's just marketing or an automated 'received' receipt without next steps),
        "new_stage": "In Process" or "Declined",
        "new_sub_stage": "HR Screen" or "Home Assignment" or "Tech Interview" or "Manager Interview" or "Offer" or null (if declined or no specific sub-stage),
        "reasoning": "Short 1 sentence explaining the classification."
    }}
    """
    try:
        response = model.generate_content(prompt)
        clean_text = response.text.strip('`').removeprefix('json\n')
        classification = json.loads(clean_text)
        return classification
    except Exception as e:
        print(f"Error classifying email with Gemini: {e}")
        return None

def connect_imap():
    email_account = os.getenv("EMAIL_ACCOUNT")
    email_password = os.getenv("EMAIL_PASSWORD")
    
    if not email_account or not email_password:
        print("Email credentials not found in environment. Skipping email check.")
        return None
        
    try:
        import socket
        socket.setdefaulttimeout(10)
        # Connect to Gmail's IMAP server
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_account, email_password)
        return mail
    except Exception as e:
        print(f"Failed to connect to email: {e}")
        return None

def get_text_from_email(msg):
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    raw = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    text += raw.decode(charset, errors='ignore')
                except Exception:
                    pass
    else:
        try:
            raw = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            text = raw.decode(charset, errors='ignore')
        except Exception:
            pass
    return text

def _check_emails_inner():
    """The actual email-check logic — called inside a timeout thread."""
    mail = connect_imap()
    if not mail:
        return
        
    try:
        mail.select("inbox")
        # Search for unseen emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            print("No new unseen emails.")
            mail.logout()
            return

        email_ids = messages[0].split()
        active_companies = get_db_companies()
        
        if not active_companies:
            print("No active job applications tracked. Skipping email check.")
            mail.logout()
            return
            
        model = setup_gemini()

        for e_id in email_ids:
            res, msg_data = mail.fetch(e_id, "(RFC822)")
            if res != "OK":
                continue
                
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    # Decode subject
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8", errors="ignore")
                        
                    sender = msg.get("From")
                    body = get_text_from_email(msg)
                    
                    # Heuristic check: does the sender or subject contain a tracked company name?
                    sender_lower = str(sender).lower()
                    subject_lower = str(subject).lower()
                    
                    matched_company = None
                    matched_jobs = []
                    
                    for comp, jobs in active_companies.items():
                        if comp in sender_lower or comp in subject_lower:
                            matched_company = comp
                            matched_jobs = jobs
                            break
                    
                    if matched_company:
                        print(f"Found potential email update from {matched_company}...")
                        classification = classify_email(model, subject, body[:2000], matched_company) # Truncate body to save tokens
                        
                        if classification and classification.get("is_relevant_update"):
                            print(f"Update: {classification.get('reasoning')}")
                            # Update all jobs for this company
                            for job in matched_jobs:
                                print(f"Updating job ID {job['id']} to {classification.get('new_stage')} / {classification.get('new_sub_stage')}")
                                database.update_job_stage(job['id'], classification.get('new_stage'), classification.get('new_sub_stage'))
                            
                            # Mark email as read by not un-flagging it (it's marked read upon fetch)
                        else:
                            print("Email deemed irrelevant to job tracking by AI.")
                    
    except Exception as e:
        print(f"Error checking emails: {e}")
    finally:
        try:
            mail.logout()
        except:
            pass

def check_emails():
    """Runs the email check with a hard 30-second timeout so it never hangs."""
    import threading
    print("Checking emails for job updates...")
    t = threading.Thread(target=_check_emails_inner, daemon=True)
    t.start()
    t.join(timeout=30)
    if t.is_alive():
        print("Email check timed out after 30s. Skipping.")

if __name__ == "__main__":
    check_emails()
