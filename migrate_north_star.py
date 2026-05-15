"""
Migration: Add selected_title and selected_thumbnail_prompt to proceso1_jobs table.
Uses raw psycopg2 with the same connection params as config.py.
"""
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'scienceluxe_1')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', '12345')
DB_PORT = os.environ.get('DB_PORT', '5432')

def run_migration():
    print(f"Connecting to {DB_HOST}:{DB_PORT}/{DB_NAME} as {DB_USER}...")
    
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    # Check existing columns
    cur.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'proceso1_jobs' 
        AND column_name IN ('selected_title', 'selected_thumbnail_prompt')
    """)
    existing = {row[0] for row in cur.fetchall()}
    
    if 'selected_title' not in existing:
        print("  Adding column: selected_title")
        cur.execute("ALTER TABLE proceso1_jobs ADD COLUMN selected_title TEXT")
    else:
        print("  Column selected_title already exists, skipping.")
    
    if 'selected_thumbnail_prompt' not in existing:
        print("  Adding column: selected_thumbnail_prompt")
        cur.execute("ALTER TABLE proceso1_jobs ADD COLUMN selected_thumbnail_prompt TEXT")
    else:
        print("  Column selected_thumbnail_prompt already exists, skipping.")
    
    cur.close()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    run_migration()
