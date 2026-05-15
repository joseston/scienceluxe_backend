"""
Migration: Add still-image motion fields to proceso4_scene_media.

These fields are used only by Proceso 4 image clips. Videos keep their
existing trim/speed/render path untouched.

Usage:
    cd software_backend
    conda activate scieluxe
    python -m aplicacion.migrations.add_image_motion_fields
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aplicacion import create_app, db
from sqlalchemy import text


def run_migration():
    app = create_app()
    with app.app_context():
        print("[1/2] Adding image_motion_preset column...")
        try:
            db.session.execute(text("""
                ALTER TABLE proceso4_scene_media
                ADD COLUMN IF NOT EXISTS image_motion_preset VARCHAR(40) DEFAULT 'auto' NOT NULL
            """))
            db.session.commit()
            print("  -> image_motion_preset ready")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add image_motion_preset column: {e}")

        print("[2/2] Adding image_motion_intensity column...")
        try:
            db.session.execute(text("""
                ALTER TABLE proceso4_scene_media
                ADD COLUMN IF NOT EXISTS image_motion_intensity VARCHAR(20) DEFAULT 'medium' NOT NULL
            """))
            db.session.commit()
            print("  -> image_motion_intensity ready")
        except Exception as e:
            db.session.rollback()
            print(f"  -> WARNING: Could not add image_motion_intensity column: {e}")

        print("\n=== image motion fields migration complete ===")


if __name__ == '__main__':
    run_migration()
