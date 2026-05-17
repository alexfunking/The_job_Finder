"""
Phase 4: Database & Logic
Handles local SQLite database persistence and de-duplication.
"""
import sqlite3
from datetime import datetime

DB_NAME = "jobs.db"

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
        
    # we can ignore the old 'status' column going forward, or drop it in a full rebuild.
    
    conn.commit()
    conn.close()

def is_job_processed(url: str) -> bool:
    """Checks if a job URL is already in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM jobs WHERE url = ?", (url,))
    result = cursor.fetchone()
    conn.close()
    return bool(result)

def add_job(title: str, company: str, url: str, ai_summary: str = None, stage: str = 'To Apply'):
    """Adds a new job to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    date_found = datetime.now().isoformat()
    
    try:
        cursor.execute("""
            INSERT INTO jobs (title, company, url, date_found, ai_summary, stage)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, company, url, date_found, ai_summary, stage))
        conn.commit()
    except sqlite3.IntegrityError:
        # Handle case where URL already exists
        pass
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

if __name__ == "__main__":
    init_db()
