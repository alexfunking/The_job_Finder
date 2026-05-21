"""
Phase 2.5: Email Progress Tracker (v2)
Monitors job application emails with smarter parsing and broader provider support.
"""
import os
import re
import time
import json
import imaplib
import email
from email.header import decode_header
import logging
from typing import Optional, Dict, List, Tuple
from functools import lru_cache
from datetime import datetime, timedelta

# Optional: Google Gemini for classification
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from db import database

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider configuration (supports Gmail, Outlook, Yahoo, custom IMAP)
# ---------------------------------------------------------------------------
EMAIL_PROVIDERS = {
    "gmail":       {"host": "imap.gmail.com", "port": 993, "ssl": True},
    "outlook":     {"host": "outlook.office365.com", "port": 993, "ssl": True},
    "yahoo":       {"host": "imap.mail.yahoo.com", "port": 993, "ssl": True},
    "icloud":      {"host": "imap.mail.me.com", "port": 993, "ssl": True},
}


def _detect_provider(email_address: str) -> Tuple[str, dict]:
    """Detect email provider based on domain."""
    domain = email_address.split("@")[-1].lower() if "@" in email_address else ""
    if "gmail.com" in domain:
        return "gmail", EMAIL_PROVIDERS["gmail"]
    elif "outlook" in domain or "office365" in domain or "live." in domain or "hotmail." in domain:
        return "outlook", EMAIL_PROVIDERS["outlook"]
    elif "yahoo" in domain:
        return "yahoo", EMAIL_PROVIDERS["yahoo"]
    elif "icloud.com" in domain or "me.com" in domain:
        return "icloud", EMAIL_PROVIDERS["icloud"]
    else:
        # Default to Gmail for unknown providers
        return "gmail", EMAIL_PROVIDERS["gmail"]


def _get_db_companies() -> Dict[str, List[dict]]:
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


# ---------------------------------------------------------------------------
# Gemini setup
# ---------------------------------------------------------------------------
_GEMINI_MODEL = None


def setup_gemini():
    """Initialize Gemini model with API key."""
    global _GEMINI_MODEL
    if _GEMINI_MODEL is not None:
        return _GEMINI_MODEL

    if not GEMINI_AVAILABLE:
        raise ValueError("google-generativeai package not installed.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    _GEMINI_MODEL = genai.GenerativeModel('gemini-2.5-flash')
    return _GEMINI_MODEL


def classify_email(model, email_subject: str, email_body: str, company_name: str) -> Optional[dict]:
    """Classify an email using Gemini."""
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
        logger.error("Error classifying email with Gemini: %s", e)
        return None


# ---------------------------------------------------------------------------
# IMAP connection
# ---------------------------------------------------------------------------
def connect_imap() -> Optional[imaplib.IMAP4]:
    """Connect to the email provider's IMAP server."""
    email_account = os.getenv("EMAIL_ACCOUNT")
    email_password = os.getenv("EMAIL_PASSWORD")

    if not email_account or not email_password:
        logger.warning("Email credentials not found in environment. Skipping email check.")
        return None

    provider_name, config = _detect_provider(email_account)
    logger.debug("Detected provider: %s", provider_name)

    try:
        import socket
        socket.setdefaulttimeout(10)

        if config["ssl"]:
            mail = imaplib.IMAP4_SSL(config["host"], config["port"])
        else:
            mail = imaplib.IMAP4(config["host"], config["port"])

        mail.login(email_account, email_password)
        logger.info("Successfully connected to %s IMAP", config["host"])
        return mail
    except Exception as e:
        logger.error("Failed to connect to email (%s): %s", config["host"], e)
        return None


# ---------------------------------------------------------------------------
# Email text extraction
# ---------------------------------------------------------------------------
def get_text_from_email(msg) -> str:
    """Extract plain text from an email message, handling multipart."""
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


def _match_company(sender: str, subject: str, active_companies: dict) -> Tuple[Optional[str], Optional[dict]]:
    """
    Match email against tracked companies using multiple heuristics.
    """
    sender_lower = str(sender).lower()
    subject_lower = str(subject).lower()

    # 1. Direct match: sender/subject contains company name
    for comp_name in active_companies:
        if comp_name in sender_lower or comp_name in subject_lower:
            return comp_name, active_companies[comp_name]

    # 2. Fuzzy match: company name parts
    for comp_name in active_companies:
        parts = comp_name.split(" ")
        for part in parts:
            if len(part) > 2 and part in sender_lower:
                return comp_name, active_companies[comp_name]

    # 3. Look for generic job-board patterns that might map to companies
    generic_indicators = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "glassdoor": "Glassdoor",
    }
    for indicator, _ in generic_indicators.items():
        if indicator in sender_lower:
            # Too generic, skip
            pass

    return None, None


# ---------------------------------------------------------------------------
# Email scanning with pagination and dedup
# ---------------------------------------------------------------------------
def _check_emails_inner():
    """Core email-check logic."""
    mail = connect_imap()
    if not mail:
        return

    try:
        mail.select("inbox")
        status, messages = mail.search(None, "(UNSEEN)")
        if status != "OK" or not messages[0]:
            logger.info("No new emails to process.")
            try:
                mail.logout()
            except:
                pass
            return

        email_ids = messages[0].split()
        active_companies = _get_db_companies()

        if not active_companies:
            logger.info("No active job applications tracked. Skipping email check.")
            try:
                mail.logout()
            except:
                pass
            return

        try:
            model = setup_gemini()
        except Exception as e:
            logger.error("Failed to set up Gemini: %s. Skipping email classification.", e)
            try:
                mail.logout()
            except:
                pass
            return

        for e_id in email_ids:
            try:
                res, msg_data = mail.fetch(e_id, "(RFC822)")
                if res != "OK":
                    continue

                for response_part in msg_data:
                    if not isinstance(response_part, tuple):
                        continue

                    msg = email.message_from_bytes(response_part[1])

                    # Decode subject
                    decoded = decode_header(msg.get("Subject"))
                    subject = decoded[0][0] if decoded else ""
                    encoding = decoded[0][1] if decoded and len(decoded[0]) > 1 else None
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8", errors="ignore")

                    sender = msg.get("From")
                    body = get_text_from_email(msg)

                    matched_company, matched_jobs = _match_company(sender, subject, active_companies)

                    if matched_company:
                        logger.info("Found potential email update from %s...", matched_company)
                        classification = classify_email(model, subject, body[:2000], matched_company)

                        if classification and classification.get("is_relevant_update"):
                            new_stage = classification.get("new_stage")
                            new_sub_stage = classification.get("new_sub_stage")
                            reason = classification.get("reasoning")
                            logger.info("Update: %s", reason)

                            for job in matched_jobs:
                                logger.info("Updating job ID %d to %s / %s",
                                           job['id'], new_stage, new_sub_stage)
                                database.update_job_stage(job['id'], new_stage, new_sub_stage)
                        else:
                            logger.info("Email from %s deemed irrelevant.", matched_company)
                    else:
                        logger.debug("No match found for email from: %s", sender)

            except Exception as e:
                logger.error("Error processing email: %s", e)
                continue

    except Exception as e:
        logger.error("Error during email checking: %s", e)
    finally:
        try:
            mail.logout()
        except:
            pass


def check_emails(timeout_seconds: int = 40):
    """Runs the email check with a configurable timeout."""
    import threading
    logger.info("Checking emails for job updates (timeout=%ds)...", timeout_seconds)
    t = threading.Thread(target=_check_emails_inner, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        logger.warning("Email check timed out after %ds. Skipping.", timeout_seconds)
    else:
        logger.info("Email check completed successfully.")


if __name__ == "__main__":
    check_emails()
