"""Diagnostic: inspect clip_library_items and proceso4_scene_media state."""
from aplicacion import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    # 0. Check which columns exist
    cols = db.session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'clip_library_items' ORDER BY ordinal_position
    """)).fetchall()
    col_names = [c[0] for c in cols]
    print("=== clip_library_items columns ===")
    print(", ".join(col_names))
    has_embedding = 'embedding' in col_names
    has_search_text = 'search_text' in col_names

    # Check pgvector extension
    pgv = db.session.execute(text(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    )).fetchone()
    print(f"pgvector extension: {'YES' if pgv else 'NO'}")
    print(f"embedding column: {'YES' if has_embedding else 'NO'}")
    print(f"search_text column: {'YES' if has_search_text else 'NO'}")

    # 1. Clip library stats (conditional on columns)
    emb_part = "COUNT(embedding) AS with_embedding," if has_embedding else "0 AS with_embedding,"
    fts_part = "COUNT(search_text) AS with_fts" if has_search_text else "0 AS with_fts"
    r = db.session.execute(text(f"""
        SELECT COUNT(*) AS total,
               {emb_part}
               COUNT(visual_description) AS with_desc,
               {fts_part}
        FROM clip_library_items
    """)).fetchone()
    print("\n=== clip_library_items stats ===")
    print(f"Total: {r[0]}, With embedding: {r[1]}, With description: {r[2]}, With FTS: {r[3]}")

    # 2. Orphan scene media per project
    rows = db.session.execute(text("""
        SELECT proceso1_job_id, COUNT(*) AS clips, COUNT(library_clip_id) AS linked
        FROM proceso4_scene_media
        GROUP BY proceso1_job_id ORDER BY proceso1_job_id
    """)).fetchall()
    print("\n=== proceso4_scene_media per project ===")
    print(f"{'PID':>6} {'Total':>8} {'Linked':>8} {'Orphans':>8}")
    for r in rows:
        print(f"{r[0]:>6} {r[1]:>8} {r[2]:>8} {r[1]-r[2]:>8}")

    # 3. File paths distribution
    rows2 = db.session.execute(text("""
        SELECT LEFT(file_path, 50) AS prefix, COUNT(*)
        FROM proceso4_scene_media
        GROUP BY LEFT(file_path, 50) ORDER BY COUNT(*) DESC
        LIMIT 15
    """)).fetchall()
    print("\n=== file_path prefixes (scene_media) ===")
    for r in rows2:
        print(f"  {r[1]:>4}x  {r[0]}")

    # 4. All library clips detail
    emb_col = "embedding IS NOT NULL as has_emb," if has_embedding else "false as has_emb,"
    fts_col = "search_text IS NOT NULL as has_fts," if has_search_text else "false as has_fts,"
    rows3 = db.session.execute(text(f"""
        SELECT id, original_filename, visual_type, 
               visual_description IS NOT NULL as has_desc,
               {emb_col}
               {fts_col}
               source_type, usage_count,
               LEFT(file_path, 60) as fpath
        FROM clip_library_items ORDER BY id
    """)).fetchall()
    print(f"\n=== All library clips ({len(rows3)} total) ===")
    for r in rows3:
        fname = (r[1] or "?")[:55]
        print(f"  ID={r[0]:>3} | {fname:<55} | type={r[2] or '-':>12} | desc={r[3]} emb={r[4]} fts={r[5]} | src={r[6]} used={r[7]}")
        print(f"         path={r[8]}")

    # 5. Orphan scene media details (no library_clip_id)
    orphans = db.session.execute(text("""
        SELECT id, proceso1_job_id, scene_num, original_filename, media_type,
               LEFT(file_path, 70) as fpath
        FROM proceso4_scene_media
        WHERE library_clip_id IS NULL
        ORDER BY proceso1_job_id, scene_num
        LIMIT 50
    """)).fetchall()
    print(f"\n=== Orphan scene_media (no library link) — first 50 of {len(orphans)} ===")
    for r in orphans:
        fname = (r[3] or "?")[:40]
        print(f"  sm_id={r[0]:>4} pid={r[1]:>3} scene={r[2]:>3} | {fname:<40} | {r[4]} | {r[5]}")
