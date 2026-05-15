"""
Migration: Add transition_sound column to proceso4_scene_media.

Stores the filename of an optional sound effect to play during clip transitions.
The file references an audio file from the user's shared SFX folder.

Usage:
    cd software_backend
    conda activate scienceluxe
    python -m aplicacion.migrations.add_transition_sound
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aplicacion import create_app, db
from sqlalchemy import text


def run_migration():
    app = create_app()
    with app.app_context():
        print("[1/1] Adding transition_sound column to proceso4_scene_media...")
        try:
            db.session.execute(text("""
                ALTER TABLE proceso4_scene_media
                ADD COLUMN IF NOT EXISTS transition_sound VARCHAR(500)
            """))
            db.session.commit()
            print("  -> transition_sound column added successfully")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add transition_sound column: {e}")

        print("\n=== transition_sound migration complete ===")


if __name__ == '__main__':
    run_migration()
