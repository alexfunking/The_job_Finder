"""
Geo Filter - Hard rules to remove clearly non-Israeli and irrelevant jobs from 'To Apply'.
Runs after recheck_jobs.py for a deterministic second pass.
"""
import sqlite3
import json
import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")

# Locations that are clearly NOT within 2hr drive of Rishon LeZion
REJECTED_LOCATIONS = [
    "usa", "united states", "u.s.", "new york", "san francisco", "california",
    "texas", "seattle", "boston", "chicago", "los angeles", "austin",
    "canada", "toronto", "vancouver",
    "uk", "united kingdom", "london", "manchester",
    "germany", "berlin", "munich",
    "france", "paris",
    "netherlands", "amsterdam",
    "india", "bangalore", "hyderabad", "mumbai", "delhi",
    "australia", "sydney", "melbourne",
    "singapore",
    "eilat",       # extremely far (4 hours away) - strictly rejected
    "europe",
    "north america",
    "remote (us only)", "remote (usa only)", "us remote", "usa remote",
    "remote (uk only)", "remote (eu only)",
    ", ny", ", ca", ", tx", ", ma", ", il", ", wa", ", fl", ", co", ", nj", ", ga", ", md", ", va",
]

# Keywords in title/company that strongly suggest overseas positions or physical summer camps
OVERSEAS_COMPANY_PATTERNS = [
    "university of california", "ucsb", "iowa", "teachiowa",
    "american credit", "amazon.com services llc", "goodreads llc",
    "mod op", "penn state", "pennsylvania", "purdue", "mit ", "stanford",
    "laurel hill school", "cam edu", "summer camp", "camp counselor", "camp specialist",
    "uc berkeley", "carnegie mellon", "harvard", "yale", "princeton", "columbia",
    "university of ", "college of ", "institute of technology", "polytechnic",
    "university hospital", "medical center", "health system",
    "amazon web services", "aws inc", "facebook", "meta platforms", "google llc",
    "preschool", "kindergarten",
]

def is_overseas(title: str, company: str, location: str) -> bool:
    title_lower = title.lower()
    company_lower = company.lower()
    location_lower = location.lower()

    # Check location field
    for bad_loc in REJECTED_LOCATIONS:
        if bad_loc in location_lower:
            return True

    # Check for company patterns that are clearly overseas
    for pattern in OVERSEAS_COMPANY_PATTERNS:
        if pattern in company_lower or pattern in title_lower:
            return True

    # Smart check for university/college that is not Israeli
    if "university" in company_lower or "college" in company_lower:
        israeli_unis = ["tel aviv", "technion", "hebrew", "bar ilan", "ariel", "haifa", "reichman", "idc", "open university", "weizmann"]
        is_israeli = any(uni in company_lower for uni in israeli_unis)
        if not is_israeli:
            return True

    return False

def pre_filter_job(job: dict) -> tuple[bool, str]:
    """
    Checks if a job violates the strict location or priority (no professional experience) rules.
    Returns (is_rejected, reason_string)
    """
    title = job.get('title', '').strip()
    company = job.get('company', '').strip()
    location = job.get('location', '').strip()
    description = job.get('description', '').strip()
    
    title_lower = title.lower()
    company_lower = company.lower()
    location_lower = location.lower()
    desc_lower = description.lower()
    
    # 1. GEOGRAPHICAL FILTER
    # Check if location contains any rejected locations
    for loc in REJECTED_LOCATIONS:
        if loc in location_lower:
            return True, f"Location '{location}' matches rejected pattern '{loc}'"
            
    # Check for overseas company patterns
    for comp in OVERSEAS_COMPANY_PATTERNS:
        if comp in company_lower or comp in title_lower:
            return True, f"Company/Title matches rejected overseas pattern '{comp}'"
            
    # Smart check for non-Israeli university
    if "university" in company_lower or "college" in company_lower:
        israeli_unis = ["tel aviv", "technion", "hebrew", "bar ilan", "ariel", "haifa", "reichman", "idc", "open university", "weizmann"]
        if not any(uni in company_lower for uni in israeli_unis):
            return True, f"Non-Israeli university: '{company}'"
            
    # 2. PRIORITY & EXPERIENCE FILTER
    # Rejection keywords for seniority
    import re
    seniority_keywords = ["senior", "sr.", "lead", "principal", "architect", "manager", "director", "vp", "head", "staff"]
    for word in seniority_keywords:
        # Check that we don't reject e.g. "student team lead" if they explicitly wanted a student
        pattern = rf"\b{word}\b"
        if re.search(pattern, title_lower):
            if "student" not in title_lower and "intern" not in title_lower:
                return True, f"Title contains seniority keyword '{word}'"
                
    # Check for years of experience requirement in title or description snippet
    # Only reject if it explicitly requires 3 or more years of experience (e.g. 3+ years, 3 years, etc.)
    # Allowing up to 2 years of experience (like 1+, 2, or 2+ years) since tech companies are often flexible
    exp_patterns = [
        r'\b(?:[3-9]|\d{2})\+\s*(?:years|yrs)\b',
        r'\b(?:[3-9]|\d{2})\s*(?:years|yrs)\s*(?:of\s+)?experience\b',
        r'\b(?:[3-9]|\d{2})-(?:[4-9]|\d{2})\s*(?:years|yrs)\b',
        r'\b(?:three|four|five|six|seven|eight|nine|ten)\s*(?:years|yrs)\s*(?:of\s+)?experience\b'
    ]
    for pattern in exp_patterns:
        if re.search(pattern, title_lower) or re.search(pattern, desc_lower):
            return True, "Requires prior professional experience (3+ years)"
            
    return False, ""

def run_geo_filter() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM jobs WHERE stage = 'To Apply'")
    jobs = cursor.fetchall()

    print(f"Running geo-filter on {len(jobs)} 'To Apply' jobs...\n")

    filtered_count = 0
    kept_count = 0

    for row in jobs:
        job_id = row['id']
        title = row['title']
        company = row['company']
        ai_str = row['ai_summary']
        
        # Read the scraped location column if it exists in the row keys
        scraped_loc = row['location'] if 'location' in row.keys() else 'Not specified'

        # Extract AI location if present
        ai_loc = "Not specified"
        try:
            if ai_str:
                d = json.loads(ai_str)
                ai_loc = d.get('location', 'Not specified')
        except Exception:
            pass

        # Try scraped_loc first, then fallback to ai_loc
        location = scraped_loc if scraped_loc and scraped_loc != "Not specified" else ai_loc
        
        # Build a temporary job dict for pre_filter_job
        job_dict = {
            "title": title,
            "company": company,
            "location": location,
            "description": ai_str or "" # Pass AI summary JSON containing key requirements
        }
        
        is_rejected, reason = pre_filter_job(job_dict)

        if is_rejected:
            print(f"  [FILTERED] [{location}]: {title} @ {company} | Reason: {reason}")
            cursor.execute(
                "UPDATE jobs SET stage = 'Irrelevant' WHERE id = ?",
                (job_id,)
            )
            filtered_count += 1
        else:
            print(f"  [KEPT]     [{location}]: {title} @ {company}")
            kept_count += 1

    conn.commit()
    conn.close()

    print(f"\n=== Geo-filter complete ===")
    print(f"Filtered out: {filtered_count} overseas/irrelevant jobs")
    print(f"Remaining in 'To Apply': {kept_count} jobs")
    return filtered_count

if __name__ == "__main__":
    run_geo_filter()
