"""One-time repair: backfill search_text for existing library clips."""
from aplicacion import create_app, db
from sqlalchemy import text
from aplicacion.models.clip_library import ClipLibraryItem

app = create_app()
with app.app_context():
    clips = ClipLibraryItem.query.filter(
        text('search_text IS NULL')
    ).all()
    print(f'Reparando {len(clips)} clips sin search_text...')
    for clip in clips:
        parts = ' '.join(filter(None, [
            clip.visual_description or '',
            clip.physical_composition or '',
            clip.visual_type or '',
            ' '.join(clip.keywords or []),
            ' '.join(clip.tags or []),
            clip.original_filename or '',
        ]))
        if parts.strip():
            db.session.execute(
                text("UPDATE clip_library_items SET search_text = to_tsvector('english', :txt) WHERE id = :cid"),
                {'txt': parts, 'cid': clip.id}
            )
            print(f'  clip {clip.id} ({clip.original_filename}): OK')
    db.session.commit()
    print('Listo.')
