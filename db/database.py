"""
Phase 4: Database & Logic
Handles local SQLite database persistence and de-duplication.
"""
import sqlite3
import logging
import os
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# jobs.db stays in the root folder, so we go up one directory from this file
DB_NAME = os.path.join(os.path.dirname(__file__), "..", "jobs.db")
logger = logging.getLogger(__name__)

# Tracking parameters to strip before deduplication
_TRACKING_PARAMS = {
    "trackingId", "trk", "ref", "utm_source", "utm_medium",
    "utm_campaign", "utm_content", "source", "si", "currentJobId",
    "recommended_job", "lipi", "midToken", "rc", "vertical", "searchId",
}

def _normalize_url(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for p in _TRACKING_PARAMS:
            qs.pop(p, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))
    except Exception:
        return url


def init_db():
    """Initializes the database schema."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            date_found TEXT NOT NULL,
            ai_summary TEXT,
            status TEXT DEFAULT 'new'
        )
    """)
    
    # Run migration to add stage and sub_stage if they don't exist
    columns = [col[1] for col in cursor.execute('PRAGMA table_info(jobs)').fetchall()]
    
    if 'stage' not in columns:
        # Default all existing relevant jobs to 'To Apply', others to 'Irrelevant'
        cursor.execute("ALTER TABLE jobs ADD COLUMN stage TEXT DEFAULT 'To Apply'")
        cursor.execute("UPDATE jobs SET stage = 'Irrelevant' WHERE ai_summary LIKE 'Irrelevant:%' OR ai_summary LIKE '%\"is_relevant\": false%'")
        
    if 'sub_stage' not in columns:
        cursor.execute("ALTER TABLE jobs ADD COLUMN sub_stage TEXT")
        
    if 'location' not in columns:
        cursor.execute("ALTER TABLE jobs ADD COLUMN location TEXT DEFAULT 'Not specified'")
        
    # we can ignore the old 'status' column going forward, or drop it in a full rebuild.
    
    conn.commit()
    conn.close()

def is_job_processed(url: str, title: str = None, company: str = None) -> bool:
    """Checks if a job is already in the database by normalized URL OR by title+company."""
    norm_url = _normalize_url(url)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Primary check: normalized URL match
    cursor.execute("SELECT 1 FROM jobs WHERE url = ?", (norm_url,))
    if cursor.fetchone():
        conn.close()
        return True
    # Secondary check: same title + company (case-insensitive)
    if title and company:
        cursor.execute(
            "SELECT 1 FROM jobs WHERE LOWER(TRIM(title)) = LOWER(TRIM(?)) AND LOWER(TRIM(company)) = LOWER(TRIM(?))",
            (title, company)
        )
        if cursor.fetchone():
            conn.close()
            return True
    conn.close()
    return False

def add_job(title: str, company: str, url: str, location: str = 'Not specified', ai_summary: str = None, stage: str = 'To Apply'):
    """Adds a new job to the database. Normalizes the URL to avoid tracking-param duplicates."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    date_found = datetime.now().isoformat()
    norm_url = _normalize_url(url)

    try:
        cursor.execute("""
            INSERT INTO jobs (title, company, url, location, date_found, ai_summary, stage)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, company, norm_url, location, date_found, ai_summary, stage))
        conn.commit()
    except sqlite3.IntegrityError:
        logger.debug("Duplicate job ignored: %s", norm_url)
    finally:
        conn.close()

def get_jobs_by_stage(stage: str):
    """Fetches all jobs for a given stage."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE stage = ? ORDER BY date_found DESC", (stage,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_job_stage(job_id: int, new_stage: str, new_sub_stage: str = None):
    """Updates the stage and sub_stage of a job."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE jobs 
        SET stage = ?, sub_stage = ?
        WHERE id = ?
    """, (new_stage, new_sub_stage, job_id))
    conn.commit()
    conn.close()

def deduplicate_jobs() -> int:
    """Removes duplicate jobs (same title+company), keeping the best record.
    Priority: Applied > To Apply > Irrelevant. Within same stage, keeps highest match_score.
    Returns the number of duplicate rows removed.
    """
    import json as _json
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    stage_priority = {'Applied': 3, 'To Apply': 2, 'Irrelevant': 1}

    # Find all groups with duplicates
    cursor.execute("""
        SELECT LOWER(TRIM(title)) as norm_title, LOWER(TRIM(company)) as norm_company,
               COUNT(*) as cnt, GROUP_CONCAT(id) as ids
        FROM jobs
        GROUP BY norm_title, norm_company
        HAVING COUNT(*) > 1
    """)
    groups = cursor.fetchall()

    removed = 0
    for group in groups:
        raw_ids = [int(i) for i in group['ids'].split(',')]
        # Fetch full rows for this group
        placeholders = ','.join('?' * len(raw_ids))
        cursor.execute(f"SELECT * FROM jobs WHERE id IN ({placeholders})", raw_ids)
        rows = cursor.fetchall()

        def row_score(row):
            stage_val = stage_priority.get(row['stage'] or 'Irrelevant', 1)
            match_score = 0
            try:
                if row['ai_summary']:
                    match_score = int(_json.loads(row['ai_summary']).get('match_score', 0))
            except Exception:
                pass
            return (stage_val, match_score)

        # Sort: best record first
        sorted_rows = sorted(rows, key=row_score, reverse=True)
        keep_id = sorted_rows[0]['id']
        delete_ids = [r['id'] for r in sorted_rows[1:]]

        if delete_ids:
            placeholders = ','.join('?' * len(delete_ids))
            cursor.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", delete_ids)
            removed += len(delete_ids)

    conn.commit()
    conn.close()
    return removed

def cleanup_low_scoring_jobs() -> int:
    """Moves any job in 'To Apply' stage that has a match score < 70 and is_relevant is False (or missing)
    to the 'Irrelevant' stage. Corrects leftovers from the old default-stage bug.
    Returns the number of jobs moved.
    """
    import json as _json
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, ai_summary FROM jobs WHERE stage = 'To Apply'")
    rows = cursor.fetchall()
    
    moved = 0
    for row in rows:
        job_id = row['id']
        ai_summary_str = row['ai_summary']
        if ai_summary_str:
            try:
                eval_data = _json.loads(ai_summary_str)
                score = int(eval_data.get('match_score', 0))
                is_relevant = eval_data.get('is_relevant', False) or score >= 70
                if not is_relevant:
                    cursor.execute("UPDATE jobs SET stage = 'Irrelevant' WHERE id = ?", (job_id,))
                    moved += 1
            except Exception:
                pass
                
    conn.commit()
    conn.close()
    return moved

if __name__ == "__main__":
    init_db()
