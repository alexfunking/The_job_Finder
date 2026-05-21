import sqlite3, json, os

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Find duplicates by title+company
c.execute("""
    SELECT title, company, COUNT(*) as cnt, GROUP_CONCAT(id) as ids, GROUP_CONCAT(stage) as stages
    FROM jobs
    GROUP BY LOWER(TRIM(title)), LOWER(TRIM(company))
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
""")
rows = c.fetchall()
print(f"Found {len(rows)} duplicate groups:\n")
for title, company, cnt, ids, stages in rows:
    print(f"  x{cnt} | [{stages}] | '{title}' @ '{company}'  (IDs: {ids})")

conn.close()
