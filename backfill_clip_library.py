"""
Backfill: Generate embeddings + search_text for ALL clip_library_items,
and import orphan scene_media (project 19) into the library.

Usage:
    cd software_backend
    conda activate scienceluxe
    python backfill_clip_library.py
"""
import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from aplicacion import create_app, db
from sqlalchemy import text

app = create_app()


def _compute_file_hash(filepath: str) -> str | None:
    """SHA-256 of file content. Returns None if file doesn't exist."""
    p = Path(filepath)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _filename_keywords(filename: str) -> str:
    """Extract descriptive words from a filename like 'Red_supergiant_star_orbital_drift_d9ddf54a82.mp4'."""
    name = Path(filename).stem
    # Remove trailing hash-like suffixes (hex strings at end)
    name = re.sub(r'[_-][0-9a-f]{8,}$', '', name)
    # Replace underscores/hyphens with spaces
    name = re.sub(r'[_\-]+', ' ', name)
    # Remove very short tokens and common noise
    words = [w for w in name.split() if len(w) >= 3]
    return ' '.join(words)


def phase1_backfill_existing_clips():
    """Generate embeddings and search_text for all existing clip_library_items."""
    from aplicacion.services.embedding_service import (
        build_clip_text, extract_keywords, generate_embedding,
    )
    from aplicacion.models.clip_library import ClipLibraryItem

    clips = ClipLibraryItem.query.order_by(ClipLibraryItem.id).all()
    total = len(clips)
    logger.info(f"Phase 1: Backfilling {total} existing library clips")

    success_emb = 0
    success_fts = 0
    errors = 0

    for i, clip in enumerate(clips, 1):
        try:
            changed = False

            # 1. Ensure keywords
            if not clip.keywords:
                extra = _filename_keywords(clip.original_filename or '')
                clip.keywords = extract_keywords(
                    clip.visual_description or '',
                    clip.physical_composition or '',
                    extra,
                )
                changed = True

            # 2. Build text (include filename keywords)
            fname_kw = _filename_keywords(clip.original_filename or '')
            all_keywords = list(clip.keywords or [])
            # Add filename words to keywords if not already present
            for w in fname_kw.lower().split():
                if w not in all_keywords and len(w) >= 3:
                    all_keywords.append(w)

            clip_text = build_clip_text(
                visual_description=clip.visual_description or '',
                physical_composition=clip.physical_composition or '',
                visual_type=clip.visual_type or '',
                keywords=all_keywords,
            )

            # 3. Generate embedding if missing
            has_embedding = db.session.execute(
                text("SELECT embedding IS NOT NULL FROM clip_library_items WHERE id = :cid"),
                {"cid": clip.id},
            ).scalar()

            if not has_embedding and clip_text:
                emb = generate_embedding(clip_text)
                if emb:
                    db.session.execute(
                        text("UPDATE clip_library_items SET embedding = CAST(:emb AS vector) WHERE id = :cid"),
                        {"emb": str(emb), "cid": clip.id},
                    )
                    success_emb += 1
                    # Rate limit: Gemini API has limits
                    time.sleep(0.15)
                else:
                    logger.warning(f"  Clip {clip.id}: embedding generation returned None")

            # 4. Update search_text
            search_parts = ' '.join(filter(None, [
                clip.visual_description or '',
                clip.physical_composition or '',
                clip.visual_type or '',
                ' '.join(all_keywords),
                clip.original_filename or '',
                fname_kw,
            ]))
            if search_parts.strip():
                db.session.execute(
                    text("UPDATE clip_library_items SET search_text = to_tsvector('english', :txt) WHERE id = :cid"),
                    {"txt": search_parts, "cid": clip.id},
                )
                success_fts += 1

            if changed:
                db.session.add(clip)

            # Commit every 5 clips to avoid huge transactions
            if i % 5 == 0:
                db.session.commit()
                logger.info(f"  Progress: {i}/{total} (emb={success_emb}, fts={success_fts}, err={errors})")

        except Exception as e:
            db.session.rollback()
            logger.error(f"  Clip {clip.id} error: {e}")
            errors += 1

    db.session.commit()
    logger.info(f"Phase 1 complete: embeddings={success_emb}, fts={success_fts}, errors={errors}")
    return success_emb, success_fts, errors


def phase2_import_orphan_scene_media():
    """Import orphan proceso4_scene_media records (no library_clip_id) into the library."""
    from aplicacion.models.clip_library import ClipLibraryItem
    from aplicacion.models.proceso4 import Proceso4SceneMedia
    from aplicacion.services.embedding_service import (
        build_clip_text, extract_keywords, generate_embedding,
    )

    orphans = Proceso4SceneMedia.query.filter(
        Proceso4SceneMedia.library_clip_id.is_(None)
    ).order_by(Proceso4SceneMedia.proceso1_job_id, Proceso4SceneMedia.scene_num).all()

    total = len(orphans)
    logger.info(f"Phase 2: Importing {total} orphan scene_media records")

    linked = 0
    created = 0
    skipped = 0
    errors = 0

    for i, sm in enumerate(orphans, 1):
        try:
            file_path = sm.file_path
            if not file_path or not Path(file_path).exists():
                logger.warning(f"  sm_id={sm.id}: file not found: {file_path}")
                skipped += 1
                continue

            # Compute hash
            file_hash = _compute_file_hash(file_path)
            if not file_hash:
                skipped += 1
                continue

            # Check if already in library (dedup by hash)
            existing = ClipLibraryItem.query.filter_by(file_hash=file_hash).first()
            if existing:
                sm.library_clip_id = existing.id
                linked += 1
            else:
                # Get P3 metadata for this scene
                from aplicacion.models.proceso4 import Proceso4SubprocessState
                p3_meta = {}
                import_state = Proceso4SubprocessState.query.filter_by(
                    proceso1_job_id=sm.proceso1_job_id,
                    subprocess_key='import_timeline',
                ).first()
                if import_state:
                    tl = (import_state.output_payload or {}).get('timeline', {})
                    for s in tl.get('scenes', []):
                        if s.get('scene_num') == sm.scene_num:
                            p3_meta = {
                                'visual_description': s.get('visual_description', ''),
                                'visual_type': s.get('visual_type', ''),
                                'physical_composition': s.get('physical_composition', ''),
                            }
                            break

                # Detect duration/resolution from file if video
                vid_dur = None
                if sm.media_type == 'video':
                    vid_dur = sm.duration  # Use existing duration from scene_media

                file_size = Path(file_path).stat().st_size

                library_clip = ClipLibraryItem(
                    file_hash=file_hash,
                    original_filename=sm.original_filename,
                    file_path=file_path,
                    media_type=sm.media_type,
                    duration=vid_dur,
                    file_size_bytes=file_size,
                    visual_type=p3_meta.get('visual_type') or None,
                    visual_description=p3_meta.get('visual_description') or None,
                    physical_composition=p3_meta.get('physical_composition') or None,
                    keywords=[],
                    tags=[],
                    source_type='scene_upload',
                    source_info={'proceso1_job_id': sm.proceso1_job_id, 'scene_num': sm.scene_num},
                )
                db.session.add(library_clip)
                db.session.flush()

                sm.library_clip_id = library_clip.id
                created += 1

                # Generate keywords + embedding + FTS
                fname_kw = _filename_keywords(sm.original_filename or '')
                extra_words = fname_kw
                library_clip.keywords = extract_keywords(
                    p3_meta.get('visual_description', ''),
                    p3_meta.get('physical_composition', ''),
                    extra_words,
                )

                all_keywords = list(library_clip.keywords or [])
                for w in fname_kw.lower().split():
                    if w not in all_keywords and len(w) >= 3:
                        all_keywords.append(w)

                clip_text = build_clip_text(
                    visual_description=library_clip.visual_description or '',
                    physical_composition=library_clip.physical_composition or '',
                    visual_type=library_clip.visual_type or '',
                    keywords=all_keywords,
                )

                if clip_text:
                    emb = generate_embedding(clip_text)
                    if emb:
                        db.session.execute(
                            text("UPDATE clip_library_items SET embedding = CAST(:emb AS vector) WHERE id = :cid"),
                            {"emb": str(emb), "cid": library_clip.id},
                        )
                    time.sleep(0.15)

                # FTS
                search_parts = ' '.join(filter(None, [
                    library_clip.visual_description or '',
                    library_clip.physical_composition or '',
                    library_clip.visual_type or '',
                    ' '.join(all_keywords),
                    library_clip.original_filename or '',
                    fname_kw,
                ]))
                if search_parts.strip():
                    db.session.execute(
                        text("UPDATE clip_library_items SET search_text = to_tsvector('english', :txt) WHERE id = :cid"),
                        {"txt": search_parts, "cid": library_clip.id},
                    )

            # Commit every 5
            if i % 5 == 0:
                db.session.commit()
                logger.info(f"  Progress: {i}/{total} (created={created}, linked={linked}, skip={skipped}, err={errors})")

        except Exception as e:
            db.session.rollback()
            logger.error(f"  sm_id={sm.id} error: {e}")
            errors += 1

    db.session.commit()
    logger.info(f"Phase 2 complete: created={created}, linked={linked}, skipped={skipped}, errors={errors}")
    return created, linked, skipped, errors


def phase3_verify():
    """Run verification queries."""
    r = db.session.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(embedding) AS with_embedding,
               COUNT(visual_description) AS with_desc,
               COUNT(search_text) AS with_fts
        FROM clip_library_items
    """)).fetchone()
    logger.info(f"Library: total={r[0]}, embedding={r[1]}, description={r[2]}, fts={r[3]}")

    orphans = db.session.execute(text("""
        SELECT COUNT(*) FROM proceso4_scene_media WHERE library_clip_id IS NULL
    """)).scalar()
    logger.info(f"Remaining orphan scene_media: {orphans}")

    # Per-project breakdown
    rows = db.session.execute(text("""
        SELECT proceso1_job_id, COUNT(*), COUNT(library_clip_id)
        FROM proceso4_scene_media
        GROUP BY proceso1_job_id ORDER BY proceso1_job_id
    """)).fetchall()
    for r in rows:
        logger.info(f"  PID={r[0]}: total={r[1]}, linked={r[2]}, orphans={r[1]-r[2]}")


if __name__ == "__main__":
    with app.app_context():
        logger.info("=" * 60)
        logger.info("CLIP LIBRARY BACKFILL")
        logger.info("=" * 60)

        # Phase 1: Backfill existing clips
        phase1_backfill_existing_clips()

        # Phase 2: Import orphan scene media
        phase2_import_orphan_scene_media()

        # Phase 3: Verify
        phase3_verify()

        logger.info("=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
