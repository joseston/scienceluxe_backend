"""
Proceso 0 — Pre-Production: Title & Thumbnail Concept (The North Star)

This process runs BEFORE Proceso 1. It does NOT require a project ID.
Drafts are stored locally as JSON files in data/proceso0/.
No Gemini API calls — only prompt generation for external AI use.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, current_app

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job
from .prompt_templates import build_title_prompt, build_thumbnail_prompt

ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_IMAGE_MIMETYPES = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'webp': 'image/webp',
}


def _get_thumbnail_dir(project_id: str) -> Path:
    """Return (and create) the folder that stores the thumbnail for a given project."""
    base = Path(current_app.config.get('THUMBNAILS_DIR', r'D:\scienceluxe_2026\thumbnails'))
    project_dir = base / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

proceso0_bp = Blueprint('proceso0', __name__)
logger = logging.getLogger(__name__)


def _get_drafts_dir() -> Path:
    base = Path(__file__).resolve().parents[4] / 'data' / 'proceso0'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load_draft(draft_id: str) -> dict | None:
    path = _get_drafts_dir() / f'{draft_id}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_draft(draft: dict) -> dict:
    draft['updated_at'] = datetime.now(timezone.utc).isoformat()
    path = _get_drafts_dir() / f"{draft['id']}.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding='utf-8')
    return draft


# ---------------------------------------------------------------------------
# Draft CRUD (local JSON storage)
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts', methods=['POST'])
def create_draft():
    """Create a new draft with the user's raw idea."""
    payload = request.get_json(silent=True) or {}
    raw_idea = str(payload.get('rawIdea') or '').strip()

    if not raw_idea:
        return jsonify({'error': 'rawIdea is required'}), 400

    draft = {
        'id': str(uuid.uuid4())[:8],
        'raw_idea': raw_idea,
        'title_prompt': None,
        'selected_title': None,
        'thumbnail_prompt': None,
        'thumbnail_image_ext': None,   # set after uploading the generated thumbnail image
        'status': 'idea',  # idea → titles_generated → title_selected → thumbnail_generated → launched
        'job_id': None,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    _save_draft(draft)
    return jsonify(draft), 201


@proceso0_bp.route('/drafts', methods=['GET'])
def list_drafts():
    """List all saved drafts, newest first."""
    drafts_dir = _get_drafts_dir()
    drafts = []
    for path in sorted(drafts_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            drafts.append(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            continue
    return jsonify({'items': drafts})


@proceso0_bp.route('/drafts/<string:draft_id>', methods=['GET'])
def get_draft(draft_id: str):
    """Get a specific draft by ID."""
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404
    return jsonify(draft)


@proceso0_bp.route('/drafts/<string:draft_id>', methods=['DELETE'])
def delete_draft(draft_id: str):
    """Delete a draft."""
    path = _get_drafts_dir() / f'{draft_id}.json'
    if not path.exists():
        return jsonify({'error': 'Draft not found'}), 404
    path.unlink()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Step 1: Generate Title Prompt
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts/<string:draft_id>/generate-titles', methods=['POST'])
def generate_title_prompt(draft_id: str):
    """
    Generate the title-options prompt from the raw idea.
    Returns the prompt text — the user pastes it into an external AI.
    """
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404

    raw_idea = draft.get('raw_idea', '')
    if not raw_idea:
        return jsonify({'error': 'Draft has no raw idea'}), 400

    title_prompt = build_title_prompt(raw_idea)

    draft['title_prompt'] = title_prompt
    draft['status'] = 'titles_generated'
    _save_draft(draft)

    return jsonify(draft)


# ---------------------------------------------------------------------------
# Step 2: Save Selected Title
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts/<string:draft_id>/select-title', methods=['POST'])
def select_title(draft_id: str):
    """Save the user's chosen title."""
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404

    payload = request.get_json(silent=True) or {}
    selected_title = str(payload.get('selectedTitle') or '').strip()

    if not selected_title:
        return jsonify({'error': 'selectedTitle is required'}), 400

    draft['selected_title'] = selected_title
    draft['status'] = 'title_selected'
    _save_draft(draft)

    return jsonify(draft)


# ---------------------------------------------------------------------------
# Step 3: Generate Thumbnail Prompt
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts/<string:draft_id>/generate-thumbnail', methods=['POST'])
def generate_thumbnail_prompt(draft_id: str):
    """
    Generate the thumbnail image-generation prompt using the raw idea + selected title.
    Returns the prompt text — the user pastes it into Midjourney/Flux/etc.
    """
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404

    raw_idea = draft.get('raw_idea', '')
    selected_title = draft.get('selected_title', '')

    if not selected_title:
        return jsonify({'error': 'Primero debes seleccionar un título (select-title)'}), 400

    thumbnail_prompt = build_thumbnail_prompt(raw_idea, selected_title)

    draft['thumbnail_prompt'] = thumbnail_prompt
    draft['status'] = 'thumbnail_generated'
    _save_draft(draft)

    return jsonify(draft)


# ---------------------------------------------------------------------------
# Step 4: Upload thumbnail image (result generated externally in Midjourney/Flux)
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts/<string:draft_id>/thumbnail-image', methods=['POST'])
def upload_thumbnail_image(draft_id: str):
    """
    Upload the thumbnail image the user created in Midjourney / Flux / etc.
    Accepts: jpg, jpeg, png, webp (multipart form field: 'file').
    Stores at: {THUMBNAILS_DIR}/{draft_id}/thumbnail.{ext}
    Accessible from any process via GET /api/proceso0/drafts/{project_id}/thumbnail-image
    since draft_id == video_id == project_id across all processes.
    """
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided (field: file)'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': f'Unsupported file type. Allowed: {sorted(ALLOWED_IMAGE_EXTENSIONS)}'}), 415

    thumb_dir = _get_thumbnail_dir(draft_id)
    # Remove any previously uploaded thumbnail for this draft
    for old in thumb_dir.glob('thumbnail.*'):
        old.unlink(missing_ok=True)

    dest = thumb_dir / f'thumbnail.{ext}'
    file.save(str(dest))

    draft['thumbnail_image_ext'] = ext
    _save_draft(draft)

    logger.info('Thumbnail image uploaded for draft %s → %s', draft_id, dest)
    return jsonify(draft)


@proceso0_bp.route('/drafts/<string:draft_id>/thumbnail-image', methods=['GET'])
def serve_thumbnail_image(draft_id: str):
    """
    Serve the uploaded thumbnail image for a project.
    Accessible from any process using the shared project_id (= draft_id = video_id).
    """
    draft = _load_draft(draft_id)
    ext = (draft or {}).get('thumbnail_image_ext')

    if not ext:
        # Try to auto-discover the file in case the draft JSON is out of sync
        try:
            thumb_dir = _get_thumbnail_dir(draft_id)
            matches = list(thumb_dir.glob('thumbnail.*'))
            if matches:
                ext = matches[0].suffix.lstrip('.')
        except Exception:
            pass

    if not ext:
        return jsonify({'error': 'No thumbnail image uploaded yet'}), 404

    thumb_dir = _get_thumbnail_dir(draft_id)
    dest = thumb_dir / f'thumbnail.{ext}'
    if not dest.exists():
        return jsonify({'error': 'Thumbnail file not found on disk'}), 404

    mimetype = ALLOWED_IMAGE_MIMETYPES.get(ext, 'application/octet-stream')
    return send_file(str(dest), mimetype=mimetype, conditional=True)


# ---------------------------------------------------------------------------
# Step 5: Launch — create Proceso 1 Job from this draft
# ---------------------------------------------------------------------------

@proceso0_bp.route('/drafts/<string:draft_id>/launch', methods=['POST'])
def launch_to_proceso1(draft_id: str):
    """
    Creates a Proceso1Job from this draft and marks it as launched.
    Idempotent: if already launched, returns the existing job.
    Status lifecycle: idea → titles_generated → title_selected → thumbnail_generated → launched
    """
    draft = _load_draft(draft_id)
    if draft is None:
        return jsonify({'error': 'Draft not found'}), 404

    if draft.get('status') != 'thumbnail_generated' and draft.get('status') != 'launched':
        return jsonify({'error': 'El draft debe estar en estado thumbnail_generated para poder lanzarse'}), 400

    # Idempotent: if already launched, return existing job
    existing_job_id = draft.get('job_id')
    if existing_job_id is not None:
        job = Proceso1Job.query.get(existing_job_id)
        if job:
            return jsonify({'draft': draft, 'job': job.to_dict()})

    # Create the Proceso1Job using the draft's data
    job = Proceso1Job(
        video_id=draft['id'],          # draft.id becomes the permanent project ID
        status='draft',
        selected_title=draft.get('selected_title') or None,
        selected_thumbnail_prompt=draft.get('thumbnail_prompt') or None,
        raw_idea=draft.get('raw_idea') or None,
        draft_id=draft['id'],
    )
    db.session.add(job)
    db.session.commit()

    # Update draft to mark it as launched and store the job's PK for navigation
    draft['job_id'] = job.id
    draft['status'] = 'launched'
    _save_draft(draft)

    logger.info('Proceso 0 draft %s launched → Proceso1Job id=%s', draft_id, job.id)
    return jsonify({'draft': draft, 'job': job.to_dict()}), 201
