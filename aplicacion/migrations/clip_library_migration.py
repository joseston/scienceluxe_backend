"""
Migration: Create Clip Library tables + pgvector extension.

Run this script once against the PostgreSQL database to set up the
clip library schema, including the pgvector embedding column,
full-text search, and HNSW index.

Usage:
    cd software_backend
    conda activate scienceluxe
    python -m aplicacion.migrations.clip_library_migration
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aplicacion import create_app, db
from sqlalchemy import text


def run_migration():
    app = create_app()
    with app.app_context():
        # 1. Enable pgvector extension
        print("[1/6] Enabling pgvector extension...")
        try:
            db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.session.commit()
            print("  -> pgvector extension enabled")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not enable pgvector: {e}")
            print("  -> Install pgvector first: https://github.com/pgvector/pgvector")
            print("  -> Continuing without vector search (full-text will still work)...")

        # 2. Create tables via SQLAlchemy (models already imported)
        print("[2/6] Creating clip_library tables...")
        from aplicacion.models.clip_library import ClipLibraryItem, ClipLibraryUsage
        db.create_all()
        print("  -> Tables created")

        # 3. Add embedding column (VECTOR type not handled by SQLAlchemy)
        print("[3/6] Adding embedding column (vector(768))...")
        try:
            db.session.execute(text("""
                ALTER TABLE clip_library_items
                ADD COLUMN IF NOT EXISTS embedding vector(768)
            """))
            db.session.commit()
            print("  -> embedding column added")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add embedding column: {e}")

        # 4. Add search_text tsvector column
        print("[4/6] Adding search_text tsvector column...")
        try:
            db.session.execute(text("""
                ALTER TABLE clip_library_items
                ADD COLUMN IF NOT EXISTS search_text tsvector
            """))
            db.session.commit()
            print("  -> search_text column added")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add search_text column: {e}")

        # 5. Create HNSW index for vector similarity search
        print("[5/6] Creating HNSW index on embedding column...")
        try:
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_clip_library_embedding_hnsw
                ON clip_library_items
                USING hnsw (embedding vector_cosine_ops)
            """))
            db.session.commit()
            print("  -> HNSW index created")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not create HNSW index: {e}")

        # 6. Create GIN index for full-text search
        print("[6/6] Creating GIN index on search_text...")
        try:
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_clip_library_search_text_gin
                ON clip_library_items
                USING gin (search_text)
            """))
            db.session.commit()
            print("  -> GIN index created")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not create GIN index: {e}")

        # 7. Add library_clip_id to proceso4_scene_media if not exists
        print("[BONUS] Adding library_clip_id FK to proceso4_scene_media...")
        try:
            db.session.execute(text("""
                ALTER TABLE proceso4_scene_media
                ADD COLUMN IF NOT EXISTS library_clip_id INTEGER
                REFERENCES clip_library_items(id) ON DELETE SET NULL
            """))
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_p4_scene_media_library_clip
                ON proceso4_scene_media (library_clip_id)
            """))
            db.session.commit()
            print("  -> library_clip_id column added")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add library_clip_id: {e}")

        print("\n=== Clip Library migration complete ===")


if __name__ == '__main__':
    run_migration()
