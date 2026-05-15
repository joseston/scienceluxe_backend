"""Check pgvector availability and install if possible."""
from aplicacion import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    r = db.session.execute(text("SELECT version()")).fetchone()
    print("PG version:", r[0])
    
    # Check if pgvector is available
    rows = db.session.execute(
        text("SELECT name FROM pg_available_extensions WHERE name LIKE '%vector%'")
    ).fetchall()
    print("Available vector extensions:", [r[0] for r in rows])
    
    # Try to create
    try:
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.session.commit()
        print("pgvector extension created/confirmed!")
        
        # Now run the full migration
        print("\n--- Running full clip library migration ---")
        
        # Add embedding column
        try:
            db.session.execute(text("""
                ALTER TABLE clip_library_items
                ADD COLUMN IF NOT EXISTS embedding vector(768)
            """))
            db.session.commit()
            print("[OK] embedding column added")
        except Exception as e:
            db.session.rollback()
            print(f"[SKIP] embedding column: {e}")
        
        # Create HNSW index
        try:
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_clip_library_embedding_hnsw
                ON clip_library_items
                USING hnsw (embedding vector_cosine_ops)
            """))
            db.session.commit()
            print("[OK] HNSW index created")
        except Exception as e:
            db.session.rollback()
            print(f"[SKIP] HNSW index: {e}")
        
        # GIN index for search_text (should exist already)
        try:
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_clip_library_search_text_gin
                ON clip_library_items
                USING gin (search_text)
            """))
            db.session.commit()
            print("[OK] GIN index created")
        except Exception as e:
            db.session.rollback()
            print(f"[SKIP] GIN index: {e}")
        
        # Verify
        cols = db.session.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'clip_library_items' AND column_name IN ('embedding', 'search_text')
        """)).fetchall()
        print("\nVerification:", {c[0]: c[1] for c in cols})
        
    except Exception as e:
        db.session.rollback()
        print(f"FAILED to create pgvector: {e}")
        print("You may need to install pgvector for your PostgreSQL installation.")
