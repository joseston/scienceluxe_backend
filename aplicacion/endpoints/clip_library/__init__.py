"""
Clip Library — Central Reusable Clip Repository
=================================================
Endpoints for uploading, searching, and managing reusable video/image clips
with semantic search powered by Gemini embeddings + pgvector.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy import text, func

from aplicacion import db
from aplicacion.models.clip_library import ClipLibraryItem, ClipLibraryUsage
from aplicacion.models.proceso4 import Proceso4SceneMedia

clip_library_bp = Blueprint('clip_library', __name__)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  FFmpeg / FFprobe — reuse Proceso 4's resolved binaries              #
# ------------------------------------------------------------------ #

def _get_ffmpeg_bins():
	"""Lazy import from proceso4 to reuse the same binary resolution."""
	from aplicacion.endpoints.proceso4 import FFMPEG_BIN, FFPROBE_BIN
	return FFMPEG_BIN, FFPROBE_BIN


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _clips_dir() -> Path:
	"""Root directory for the clip library files."""
	d = Path(current_app.config.get('CLIPS_LIBRARY_DIR', r'H:\Mi unidad\Scienceluxe_clips'))
	d.mkdir(parents=True, exist_ok=True)
	return d


def _has_clip_library_column(column_name: str) -> bool:
	try:
		col_row = db.session.execute(text("""
			SELECT 1
			FROM information_schema.columns
			WHERE table_name = 'clip_library_items'
			  AND column_name = :column_name
		"""), {'column_name': column_name}).fetchone()
		return col_row is not None
	except Exception:
		db.session.rollback()
		return False


def _has_pgvector() -> bool:
	"""Check if vector search can run against the current schema."""
	try:
		ext_row = db.session.execute(
			text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
		).fetchone()
		return ext_row is not None and _has_clip_library_column('embedding')
	except Exception:
		db.session.rollback()
		return False


def _has_search_text() -> bool:
	"""Return True when the full-text search column exists."""
	return _has_clip_library_column('search_text')


def _hash_subdir(file_hash: str) -> str:
	"""First 2 chars of the hash as a subdirectory — avoids thousands of files in one folder."""
	return file_hash[:2]


def _compute_file_hash(filepath: str | Path) -> str:
	"""SHA-256 of file content."""
	h = hashlib.sha256()
	with open(filepath, 'rb') as f:
		for chunk in iter(lambda: f.read(1 << 20), b''):
			h.update(chunk)
	return h.hexdigest()


def _is_video(filename: str) -> bool:
	ext = Path(filename).suffix.lower()
	return ext in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}


def _is_image(filename: str) -> bool:
	ext = Path(filename).suffix.lower()
	return ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}


def _get_video_duration(filepath: str) -> float | None:
	"""Detect video duration via ffprobe."""
	ffmpeg_bin, ffprobe_bin = _get_ffmpeg_bins()
	try:
		result = subprocess.run(
			[ffprobe_bin, '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
			capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
		)
		if result.returncode == 0 and result.stdout:
			info = json.loads(result.stdout)
			dur = float(info.get('format', {}).get('duration', 0))
			if dur > 0:
				return dur
	except Exception:
		pass
	return None


def _get_video_resolution(filepath: str) -> tuple[int | None, int | None]:
	"""Detect video resolution via ffprobe."""
	_, ffprobe_bin = _get_ffmpeg_bins()
	try:
		result = subprocess.run(
			[ffprobe_bin, '-v', 'quiet', '-print_format', 'json', '-show_streams', filepath],
			capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
		)
		if result.returncode == 0 and result.stdout:
			info = json.loads(result.stdout)
			for s in info.get('streams', []):
				if s.get('codec_type') == 'video':
					return s.get('width'), s.get('height')
	except Exception:
		pass
	return None, None


def _generate_thumbnail(filepath: str, dest_path: str) -> bool:
	"""Extract a single frame from the middle of the video as a JPEG thumbnail."""
	ffmpeg_bin, _ = _get_ffmpeg_bins()
	try:
		dur = _get_video_duration(filepath)
		seek = max(0, (dur or 2) / 2)
		cmd = [
			ffmpeg_bin, '-y',
			'-ss', str(seek),
			'-i', filepath,
			'-vframes', '1',
			'-vf', 'scale=320:-2',
			'-q:v', '6',
			dest_path,
		]
		result = subprocess.run(cmd, capture_output=True, timeout=30)
		return result.returncode == 0 and Path(dest_path).exists()
	except Exception:
		return False


def _generate_proxy(filepath: str, dest_path: str) -> bool:
	"""Generate a 480p proxy (same pattern as Proceso4)."""
	ffmpeg_bin, _ = _get_ffmpeg_bins()
	try:
		cmd = [
			ffmpeg_bin, '-y',
			'-i', filepath,
			'-vf', 'scale=-2:480',
			'-c:v', 'libx264',
			'-preset', 'ultrafast',
			'-crf', '30',
			'-an',
			'-movflags', '+faststart',
			dest_path,
		]
		result = subprocess.run(cmd, capture_output=True, timeout=120)
		return result.returncode == 0 and Path(dest_path).exists()
	except Exception:
		return False


def _generate_assets_async(clip_id: int, original_path: str, app):
	"""Background thread: generate thumbnail, proxy, and embedding for a clip."""

	def _worker():
		with app.app_context():
			clip = ClipLibraryItem.query.get(clip_id)
			if not clip:
				return

			root = _clips_dir()
			sub = _hash_subdir(clip.file_hash)

			# Thumbnail
			if clip.media_type == 'video' and not clip.thumbnail_path:
				thumb_dir = root / 'thumbnails' / sub
				thumb_dir.mkdir(parents=True, exist_ok=True)
				thumb_path = str(thumb_dir / f"{clip.file_hash}_thumb.jpg")
				if _generate_thumbnail(original_path, thumb_path):
					clip.thumbnail_path = thumb_path

			# Proxy
			if clip.media_type == 'video' and not clip.proxy_path:
				proxy_dir = root / 'proxies' / sub
				proxy_dir.mkdir(parents=True, exist_ok=True)
				proxy_path = str(proxy_dir / f"{clip.file_hash}_proxy.mp4")
				if _generate_proxy(original_path, proxy_path):
					clip.proxy_path = proxy_path

			# For images, use the image itself as thumbnail
			if clip.media_type == 'image' and not clip.thumbnail_path:
				clip.thumbnail_path = clip.file_path

			# Persist thumbnail/proxy paths immediately so they survive embedding errors
			try:
				db.session.commit()
			except Exception:
				db.session.rollback()

			# ── Keywords + Embedding (requires pgvector) ─────────────────────
			try:
				from aplicacion.services.embedding_service import (
					build_clip_text,
					extract_keywords,
					generate_embedding,
				)
				# Auto-extract keywords if not set
				if not clip.keywords:
					clip.keywords = extract_keywords(
						clip.visual_description or '',
						clip.physical_composition or '',
					)
					db.session.commit()  # persist keywords immediately

				# Build combined text and generate embedding
				clip_text = build_clip_text(
					visual_description=clip.visual_description or '',
					physical_composition=clip.physical_composition or '',
					visual_type=clip.visual_type or '',
					keywords=clip.keywords,
				)
				if clip_text:
					emb = generate_embedding(clip_text)
					if emb:
						db.session.execute(
							text("""
								UPDATE clip_library_items
								SET embedding = CAST(:emb AS vector)
								WHERE id = :cid
							"""),
							{'emb': str(emb), 'cid': clip.id},
						)
						db.session.commit()
			except Exception as e:
				db.session.rollback()
				logger.warning(f"[ClipLib] Embedding generation failed for clip {clip_id}: {e}")

			# ── Full-text search index (always runs, no pgvector needed) ──────
			try:
				# Re-fetch clip in case keywords were updated
				clip = ClipLibraryItem.query.get(clip_id)
				if not clip:
					return
				search_parts = ' '.join(filter(None, [
					clip.visual_description or '',
					clip.physical_composition or '',
					clip.visual_type or '',
					' '.join(clip.keywords or []),
					' '.join(clip.tags or []),
					clip.original_filename or '',
				]))
				if search_parts.strip():
					db.session.execute(
						text("""
							UPDATE clip_library_items
							SET search_text = to_tsvector('english', :txt)
							WHERE id = :cid
						"""),
						{'txt': search_parts, 'cid': clip.id},
					)
					db.session.commit()
			except Exception as e:
				db.session.rollback()
				logger.warning(f"[ClipLib] Full-text index failed for clip {clip_id}: {e}")

	t = threading.Thread(target=_worker, daemon=True)
	t.start()


# ------------------------------------------------------------------ #
#  CRUD Endpoints                                                      #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/clips', methods=['POST'])
def upload_clip():
	"""Upload one or more clips to the library.

	FormData fields:
	  - file (required, multiple allowed)
	  - visual_description (optional)
	  - visual_type (optional)
	  - physical_composition (optional)
	  - keywords (optional, comma-separated or JSON array)
	  - tags (optional, comma-separated or JSON array)
	  - source_type (optional: ai_generated, recorded, stock, downloaded)
	  - source_info (optional, JSON string)
	"""
	files = request.files.getlist('file')
	if not files:
		return jsonify(error="No file provided"), 400

	visual_description = request.form.get('visual_description', '').strip()
	visual_type = request.form.get('visual_type', '').strip()
	physical_composition = request.form.get('physical_composition', '').strip()
	source_type = request.form.get('source_type', '').strip() or 'unknown'

	# Parse keywords
	kw_raw = request.form.get('keywords', '')
	try:
		keywords = json.loads(kw_raw) if kw_raw.startswith('[') else [k.strip() for k in kw_raw.split(',') if k.strip()]
	except Exception:
		keywords = [k.strip() for k in kw_raw.split(',') if k.strip()]

	# Parse tags
	tags_raw = request.form.get('tags', '')
	try:
		tags = json.loads(tags_raw) if tags_raw.startswith('[') else [t.strip() for t in tags_raw.split(',') if t.strip()]
	except Exception:
		tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

	# Parse source_info
	source_info_raw = request.form.get('source_info', '')
	try:
		source_info = json.loads(source_info_raw) if source_info_raw else {}
	except Exception:
		source_info = {}

	results = []
	root = _clips_dir()

	for f in files:
		if not f.filename:
			continue

		filename = f.filename
		if not (_is_video(filename) or _is_image(filename)):
			continue

		media_type = 'video' if _is_video(filename) else 'image'

		# Save to temp first, compute hash
		tmp_dir = root / '_tmp'
		tmp_dir.mkdir(parents=True, exist_ok=True)
		tmp_path = tmp_dir / f"{uuid.uuid4().hex}{Path(filename).suffix}"
		f.save(str(tmp_path))

		file_hash = _compute_file_hash(tmp_path)

		# Check deduplication
		existing = ClipLibraryItem.query.filter_by(file_hash=file_hash).first()
		if existing:
			tmp_path.unlink(missing_ok=True)
			results.append(existing.to_dict())
			continue

		# Move to content-addressed location
		sub = _hash_subdir(file_hash)
		dest_dir = root / 'originals' / sub
		dest_dir.mkdir(parents=True, exist_ok=True)
		ext = Path(filename).suffix.lower()
		dest_path = dest_dir / f"{file_hash}{ext}"
		shutil.move(str(tmp_path), str(dest_path))

		file_size = dest_path.stat().st_size

		# Detect video metadata
		duration = None
		res_w, res_h = None, None
		if media_type == 'video':
			duration = _get_video_duration(str(dest_path))
			res_w, res_h = _get_video_resolution(str(dest_path))

		clip = ClipLibraryItem(
			file_hash=file_hash,
			original_filename=filename,
			file_path=str(dest_path),
			media_type=media_type,
			duration=duration,
			resolution_w=res_w,
			resolution_h=res_h,
			file_size_bytes=file_size,
			visual_type=visual_type or None,
			visual_description=visual_description or None,
			physical_composition=physical_composition or None,
			keywords=keywords if keywords else [],
			tags=tags if tags else [],
			source_type=source_type,
			source_info=source_info if source_info else None,
		)
		db.session.add(clip)
		db.session.commit()

		# Generate thumbnail, proxy, embedding in background
		_generate_assets_async(clip.id, str(dest_path), current_app._get_current_object())

		results.append(clip.to_dict())

	return jsonify(results), 201


@clip_library_bp.route('/clips', methods=['GET'])
def list_clips():
	"""List/filter clips in the library.

	Query params: q, visual_type, source_type, tags, min_duration, max_duration,
	              is_favorite, sort_by (newest|oldest|most_used|duration), page, per_page
	"""
	q = request.args.get('q', '').strip()
	visual_type = request.args.get('visual_type', '').strip()
	source_type = request.args.get('source_type', '').strip()
	tags_raw = request.args.get('tags', '').strip()
	min_dur = request.args.get('min_duration', type=float)
	max_dur = request.args.get('max_duration', type=float)
	is_fav = request.args.get('is_favorite', '').strip().lower()
	sort_by = request.args.get('sort_by', 'newest').strip()
	page = max(1, request.args.get('page', 1, type=int))
	per_page = min(100, max(1, request.args.get('per_page', 40, type=int)))

	query = ClipLibraryItem.query

	# Filters
	if visual_type:
		query = query.filter(ClipLibraryItem.visual_type == visual_type)
	if source_type:
		query = query.filter(ClipLibraryItem.source_type == source_type)
	if tags_raw:
		tags_list = [t.strip() for t in tags_raw.split(',') if t.strip()]
		for tag in tags_list:
			query = query.filter(ClipLibraryItem.tags.contains([tag]))
	if min_dur is not None:
		query = query.filter(ClipLibraryItem.duration >= min_dur)
	if max_dur is not None:
		query = query.filter(ClipLibraryItem.duration <= max_dur)
	if is_fav in ('true', '1'):
		query = query.filter(ClipLibraryItem.is_favorite == True)

	# Full-text search
	if q:
		query = query.filter(
			text("search_text @@ plainto_tsquery('english', :q)")
		).params(q=q)

	# Sort
	if sort_by == 'oldest':
		query = query.order_by(ClipLibraryItem.created_at.asc())
	elif sort_by == 'most_used':
		query = query.order_by(ClipLibraryItem.usage_count.desc())
	elif sort_by == 'duration':
		query = query.order_by(ClipLibraryItem.duration.desc().nullslast())
	else:  # newest
		query = query.order_by(ClipLibraryItem.created_at.desc())

	total = query.count()
	items = query.offset((page - 1) * per_page).limit(per_page).all()

	return jsonify({
		'items': [c.to_dict() for c in items],
		'total': total,
		'page': page,
		'perPage': per_page,
		'totalPages': (total + per_page - 1) // per_page,
	})


@clip_library_bp.route('/clips/<int:clip_id>', methods=['GET'])
def get_clip(clip_id: int):
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	return jsonify(clip.to_dict())


@clip_library_bp.route('/clips/<int:clip_id>', methods=['PUT'])
def update_clip(clip_id: int):
	"""Update clip metadata (description, keywords, tags, favorite, visual_type)."""
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	data = request.get_json(force=True)

	if 'visualDescription' in data:
		clip.visual_description = data['visualDescription']
	if 'physicalComposition' in data:
		clip.physical_composition = data['physicalComposition']
	if 'visualType' in data:
		clip.visual_type = data['visualType']
	if 'keywords' in data:
		clip.keywords = data['keywords']
	if 'tags' in data:
		clip.tags = data['tags']
	if 'sourceType' in data:
		clip.source_type = data['sourceType']
	if 'isFavorite' in data:
		clip.is_favorite = bool(data['isFavorite'])

	db.session.commit()

	# Re-generate embedding in background
	_generate_assets_async(clip.id, clip.file_path, current_app._get_current_object())

	return jsonify(clip.to_dict())


@clip_library_bp.route('/clips/<int:clip_id>', methods=['DELETE'])
def delete_clip(clip_id: int):
	clip = ClipLibraryItem.query.get_or_404(clip_id)

	# Remove files
	for path_str in [clip.file_path, clip.thumbnail_path, clip.proxy_path]:
		if path_str:
			p = Path(path_str)
			p.unlink(missing_ok=True)

	# Remove usage records
	ClipLibraryUsage.query.filter_by(clip_id=clip_id).delete()

	# Nullify references in scene media
	Proceso4SceneMedia.query.filter_by(library_clip_id=clip_id).update({'library_clip_id': None})

	db.session.delete(clip)
	db.session.commit()

	return jsonify(ok=True)


# ------------------------------------------------------------------ #
#  File serving                                                        #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/clips/<int:clip_id>/file', methods=['GET'])
def serve_clip_file(clip_id: int):
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	p = Path(clip.file_path)
	if not p.exists():
		return jsonify(error="File not found on disk"), 404
	return send_file(str(p), mimetype='application/octet-stream')


@clip_library_bp.route('/clips/<int:clip_id>/proxy', methods=['GET'])
def serve_clip_proxy(clip_id: int):
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	proxy = clip.proxy_path
	if proxy and Path(proxy).exists():
		return send_file(proxy, mimetype='video/mp4')
	# Fallback to original
	p = Path(clip.file_path)
	if p.exists():
		return send_file(str(p), mimetype='application/octet-stream')
	return jsonify(error="File not found"), 404


@clip_library_bp.route('/clips/<int:clip_id>/thumbnail', methods=['GET'])
def serve_clip_thumbnail(clip_id: int):
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	thumb = clip.thumbnail_path
	if thumb and Path(thumb).exists():
		return send_file(thumb, mimetype='image/jpeg')
	# For images, serve the original
	if clip.media_type == 'image' and Path(clip.file_path).exists():
		return send_file(clip.file_path, mimetype='application/octet-stream')
	# Try generating on-the-fly if the original video exists
	if clip.media_type == 'video' and clip.file_path and Path(clip.file_path).exists():
		try:
			root = _clips_dir()
			sub = _hash_subdir(clip.file_hash)
			thumb_dir = root / 'thumbnails' / sub
			thumb_dir.mkdir(parents=True, exist_ok=True)
			thumb_path = str(thumb_dir / f"{clip.file_hash}_thumb.jpg")
			if _generate_thumbnail(clip.file_path, thumb_path):
				clip.thumbnail_path = thumb_path
				db.session.commit()
				return send_file(thumb_path, mimetype='image/jpeg')
		except Exception:
			db.session.rollback()
	return jsonify(error="Thumbnail not available"), 404


# ------------------------------------------------------------------ #
#  Semantic Search                                                     #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/search', methods=['POST'])
def search_clips():
	"""Semantic + full-text search combined.

	Body: { query: string, visual_type?: string, min_duration?: float,
	        max_duration?: float, limit?: int, threshold?: float }
	"""
	data = request.get_json(force=True)
	query_text = (data.get('query') or '').strip()
	if not query_text:
		return jsonify(error="Query is required"), 400

	visual_type = data.get('visual_type', '')
	min_dur = data.get('min_duration')
	max_dur = data.get('max_duration')
	limit = min(50, max(1, data.get('limit', 20)))
	threshold = data.get('threshold', 0.3)

	pgvector_available = _has_pgvector()
	query_emb = None
	if pgvector_available:
		try:
			from aplicacion.services.embedding_service import generate_query_embedding
			query_emb = generate_query_embedding(query_text)
		except Exception as e:
			logger.warning(f"[ClipLib] Query embedding unavailable, using full-text search: {e}")

	if query_emb and pgvector_available:
		# Vector similarity search via pgvector
		filters = ["embedding IS NOT NULL"]
		params: dict = {'emb': str(query_emb), 'threshold': threshold, 'lim': limit}

		if visual_type:
			filters.append("visual_type = :vtype")
			params['vtype'] = visual_type
		if min_dur is not None:
			filters.append("(duration >= :min_dur OR duration IS NULL)")
			params['min_dur'] = min_dur
		if max_dur is not None:
			filters.append("(duration <= :max_dur OR duration IS NULL)")
			params['max_dur'] = max_dur

		where_clause = " AND ".join(filters)

		sql = text(f"""
			SELECT id, 1 - (embedding <=> CAST(:emb AS vector)) AS similarity
			FROM clip_library_items
			WHERE {where_clause}
			  AND 1 - (embedding <=> CAST(:emb AS vector)) > :threshold
			ORDER BY embedding <=> CAST(:emb AS vector)
			LIMIT :lim
		""")
		rows = db.session.execute(sql, params).fetchall()
		clip_ids = [r[0] for r in rows]
		scores = {r[0]: round(float(r[1]), 4) for r in rows}
	else:
		# Fallback to full-text only
		clip_ids = []
		scores = {}

	# If no vector results, try full-text
	if not clip_ids:
		if _has_search_text():
			fts_query = ClipLibraryItem.query.filter(
				text("search_text @@ plainto_tsquery('english', :q)")
			).params(q=query_text)
			if visual_type:
				fts_query = fts_query.filter(ClipLibraryItem.visual_type == visual_type)
			clips = fts_query.limit(limit).all()
			search_type = 'fulltext'
		else:
			ilike_q = ClipLibraryItem.query
			conditions = []
			if visual_type:
				conditions.append(ClipLibraryItem.visual_type == visual_type)
			for word in query_text.split()[:8]:
				if len(word) >= 4:
					conditions.append(ClipLibraryItem.visual_description.ilike(f'%{word}%'))
					conditions.append(ClipLibraryItem.original_filename.ilike(f'%{word}%'))
			if conditions:
				ilike_q = ilike_q.filter(db.or_(*conditions))
			clips = ilike_q.limit(limit).all()
			search_type = 'ilike'
		return jsonify({
			'items': [
				{**c.to_dict(), 'similarityScore': None}
				for c in clips
			],
			'searchType': search_type,
		})

	# Fetch full objects
	clips_map = {c.id: c for c in ClipLibraryItem.query.filter(ClipLibraryItem.id.in_(clip_ids)).all()}
	results = []
	for cid in clip_ids:
		c = clips_map.get(cid)
		if c:
			results.append({**c.to_dict(), 'similarityScore': scores.get(cid)})

	return jsonify({
		'items': results,
		'searchType': 'semantic',
	})


@clip_library_bp.route('/suggest-for-scene', methods=['POST'])
def suggest_for_scene():
	"""Auto-suggest library clips for a scene based on its metadata.

	Body: { visual_description, visual_type, physical_composition, duration, limit? }
	"""
	data = request.get_json(force=True)
	visual_desc = (data.get('visual_description') or '').strip()
	visual_type = (data.get('visual_type') or '').strip()
	physical_comp = (data.get('physical_composition') or '').strip()
	scene_duration = data.get('duration', 0)
	limit = min(20, max(1, data.get('limit', 10)))

	if not visual_desc and not physical_comp and not visual_type:
		return jsonify(items=[], searchType='none')

	# Build query text combining all scene metadata.
	query_text = '\n'.join(filter(None, [visual_desc, physical_comp, visual_type]))
	query_emb = None
	pgvector_available = _has_pgvector()
	if pgvector_available:
		try:
			from aplicacion.services.embedding_service import generate_query_embedding
			query_emb = generate_query_embedding(query_text)
		except Exception as e:
			logger.warning(f"[ClipLib] Scene suggestion embedding unavailable, using full-text search: {e}")

	if not query_emb or not pgvector_available:
		# No embedding available or pgvector not installed — fall back to full-text + ILIKE
		fts_parts = ' '.join(filter(None, [visual_desc, physical_comp, visual_type]))
		clips = []

		# 1) Try full-text search with OR semantics (more lenient than plainto_tsquery AND)
		if fts_parts.strip() and _has_search_text():
			# Extract meaningful words (skip very short ones) and join with OR
			import re as _re
			words = [w for w in _re.findall(r'[a-zA-Z]{3,}', fts_parts) if w.lower() not in {
				'the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'over',
				'through', 'showing', 'revealing', 'demonstrating',
			}]
			if words:
				or_query = ' | '.join(words[:12])  # limit tokens
				fts_q = ClipLibraryItem.query.filter(
					text("search_text @@ to_tsquery('english', :q)")
				).params(q=or_query)
				if scene_duration and scene_duration > 0:
					min_dur = scene_duration * 0.4
					fts_q = fts_q.filter(
						db.or_(ClipLibraryItem.duration >= min_dur, ClipLibraryItem.duration.is_(None))
					)
				clips = fts_q.limit(limit).all()

		# 2) If FTS returned nothing, fall back to visual_type match + ILIKE on description
		if not clips:
			ilike_q = ClipLibraryItem.query
			conditions = []
			if visual_type:
				conditions.append(ClipLibraryItem.visual_type == visual_type)
			if visual_desc:
				# Use first few significant words for ILIKE
				import re as _re
				sig_words = [w for w in _re.findall(r'[a-zA-Z]{4,}', visual_desc) if w.lower() not in {
					'the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'over',
					'through', 'showing', 'revealing', 'demonstrating', 'view',
				}][:5]
				for w in sig_words:
					conditions.append(ClipLibraryItem.visual_description.ilike(f'%{w}%'))
			if conditions:
				ilike_q = ilike_q.filter(db.or_(*conditions))
			if scene_duration and scene_duration > 0:
				min_dur = scene_duration * 0.4
				ilike_q = ilike_q.filter(
					db.or_(ClipLibraryItem.duration >= min_dur, ClipLibraryItem.duration.is_(None))
				)
			clips = ilike_q.limit(limit).all()

		return jsonify({
			'items': [{**c.to_dict(), 'similarityScore': None} for c in clips],
			'searchType': 'fulltext' if _has_search_text() else 'ilike',
		})

	# --- Semantic search via pgvector ---
	filters = ["embedding IS NOT NULL"]
	params: dict = {'emb': str(query_emb), 'lim': limit, 'threshold': 0.12}

	if scene_duration and scene_duration > 0:
		min_dur = scene_duration * 0.4
		filters.append("(duration >= :min_dur OR duration IS NULL)")
		params['min_dur'] = min_dur

	where_clause = " AND ".join(filters)

	sql = text(f"""
		SELECT id, 1 - (embedding <=> CAST(:emb AS vector)) AS similarity
		FROM clip_library_items
		WHERE {where_clause}
		  AND 1 - (embedding <=> CAST(:emb AS vector)) > :threshold
		ORDER BY embedding <=> CAST(:emb AS vector)
		LIMIT :lim
	""")
	rows = db.session.execute(sql, params).fetchall()

	clip_ids = [r[0] for r in rows]
	scores = {r[0]: round(float(r[1]), 4) for r in rows}

	# --- Supplement with visual_type + FTS if semantic returned few ---
	if len(clip_ids) < limit:
		seen_ids = set(clip_ids)
		remaining = limit - len(clip_ids)

		# visual_type match
		if visual_type:
			vt_q = ClipLibraryItem.query.filter(
				ClipLibraryItem.visual_type == visual_type,
				~ClipLibraryItem.id.in_(seen_ids) if seen_ids else True,
			)
			if scene_duration and scene_duration > 0:
				min_dur = scene_duration * 0.4
				vt_q = vt_q.filter(
					db.or_(ClipLibraryItem.duration >= min_dur, ClipLibraryItem.duration.is_(None))
				)
			for c in vt_q.limit(remaining).all():
				if c.id not in seen_ids:
					clip_ids.append(c.id)
					scores[c.id] = None
					seen_ids.add(c.id)
			remaining = limit - len(clip_ids)

		# FTS fallback for remaining slots
		if remaining > 0:
			fts_parts = ' '.join(filter(None, [visual_desc, physical_comp, visual_type]))
			import re as _re
			words = [w for w in _re.findall(r'[a-zA-Z]{3,}', fts_parts) if w.lower() not in {
				'the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'over',
				'through', 'showing', 'revealing', 'demonstrating',
			}]
			if words:
				or_query = ' | '.join(words[:12])
				fts_q = ClipLibraryItem.query.filter(
					text("search_text @@ to_tsquery('english', :q)")
				).params(q=or_query)
				if seen_ids:
					fts_q = fts_q.filter(~ClipLibraryItem.id.in_(seen_ids))
				if scene_duration and scene_duration > 0:
					min_dur = scene_duration * 0.4
					fts_q = fts_q.filter(
						db.or_(ClipLibraryItem.duration >= min_dur, ClipLibraryItem.duration.is_(None))
					)
				for c in fts_q.limit(remaining).all():
					if c.id not in seen_ids:
						clip_ids.append(c.id)
						scores[c.id] = None
						seen_ids.add(c.id)

	clips_map = {c.id: c for c in ClipLibraryItem.query.filter(ClipLibraryItem.id.in_(clip_ids)).all()} if clip_ids else {}

	results = []
	for cid in clip_ids:
		c = clips_map.get(cid)
		if c:
			results.append({**c.to_dict(), 'similarityScore': scores.get(cid)})

	return jsonify({
		'items': results,
		'searchType': 'semantic',
	})


# ------------------------------------------------------------------ #
#  Use a library clip in a scene                                       #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/clips/<int:clip_id>/use-in-scene', methods=['POST'])
def use_clip_in_scene(clip_id: int):
	"""Insert a library clip into a Proceso4 scene.

	The file is NOT copied — the SceneMedia record points directly to the
	library file, keeping a single copy on disk.

	Body: { proceso1JobId, sceneNum }
	"""
	clip = ClipLibraryItem.query.get_or_404(clip_id)
	data = request.get_json(force=True)
	pid = data.get('proceso1JobId')
	scene_num = data.get('sceneNum')
	if not pid or scene_num is None:
		return jsonify(error="proceso1JobId and sceneNum required"), 400

	# Determine next clip_index for this scene
	max_idx = db.session.query(func.max(Proceso4SceneMedia.clip_index)).filter_by(
		proceso1_job_id=pid, scene_num=scene_num,
	).scalar()
	next_idx = (max_idx or 0) + 1 if max_idx is not None else 0

	# Create scene media record pointing directly to library file
	media = Proceso4SceneMedia(
		proceso1_job_id=pid,
		scene_num=scene_num,
		clip_index=next_idx,
		media_type=clip.media_type,
		original_filename=clip.original_filename,
		file_path=clip.file_path,
		duration=clip.duration,
		library_clip_id=clip.id,
	)
	# Reuse library proxy if available
	if clip.proxy_path:
		media.proxy_path = clip.proxy_path
	db.session.add(media)

	# Track usage
	clip.usage_count = (clip.usage_count or 0) + 1
	usage = ClipLibraryUsage(
		clip_id=clip.id,
		proceso1_job_id=pid,
		scene_num=scene_num,
	)
	db.session.add(usage)
	db.session.commit()

	# Update scene_media_id in usage
	usage.scene_media_id = media.id
	db.session.commit()

	return jsonify(media.to_dict()), 201


# ------------------------------------------------------------------ #
#  Stats / utility                                                     #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/stats', methods=['GET'])
def library_stats():
	"""Quick stats about the clip library."""
	total = ClipLibraryItem.query.count()
	videos = ClipLibraryItem.query.filter_by(media_type='video').count()
	images = ClipLibraryItem.query.filter_by(media_type='image').count()
	favorites = ClipLibraryItem.query.filter_by(is_favorite=True).count()
	try:
		with_embedding = db.session.execute(
			text("SELECT COUNT(*) FROM clip_library_items WHERE embedding IS NOT NULL")
		).scalar() or 0
	except Exception:
		db.session.rollback()
		with_embedding = 0

	return jsonify({
		'totalClips': total,
		'videos': videos,
		'images': images,
		'favorites': favorites,
		'withEmbedding': with_embedding,
	})


# ------------------------------------------------------------------ #
#  Repair embeddings for clips missing them                            #
# ------------------------------------------------------------------ #

@clip_library_bp.route('/repair-embeddings', methods=['POST'])
def repair_embeddings():
	"""Generate embeddings + search_text for clips that are missing them.

	Body (optional): { limit: int (default 50) }
	"""
	data = request.get_json(force=True) if request.is_json else {}
	batch_limit = min(200, max(1, data.get('limit', 50)))

	from aplicacion.services.embedding_service import (
		build_clip_text, generate_embedding, extract_keywords,
	)

	clips = ClipLibraryItem.query.filter(
		text("embedding IS NULL")
	).limit(batch_limit).all()

	repaired = 0
	errors = 0

	for clip in clips:
		try:
			kw = extract_keywords(
				visual_description=clip.visual_description or '',
				physical_composition=clip.physical_composition or '',
			)
			clip_text = build_clip_text(
				visual_description=clip.visual_description or '',
				physical_composition=clip.physical_composition or '',
				visual_type=clip.visual_type or '',
				keywords=kw,
			)
			if not clip_text:
				continue

			emb = generate_embedding(clip_text)
			if emb:
				db.session.execute(
					text("UPDATE clip_library_items SET embedding = CAST(:emb AS vector) WHERE id = :cid"),
					{'emb': str(emb), 'cid': clip.id},
				)
			if not clip.search_text:
				words = ' '.join(kw) if kw else clip_text
				db.session.execute(
					text("UPDATE clip_library_items SET search_text = to_tsvector('english', :txt) WHERE id = :cid"),
					{'txt': words, 'cid': clip.id},
				)
			repaired += 1
		except Exception:
			logger.exception("Failed to repair clip %s", clip.id)
			errors += 1

	db.session.commit()

	remaining = db.session.execute(
		text("SELECT COUNT(*) FROM clip_library_items WHERE embedding IS NULL")
	).scalar() or 0

	return jsonify({
		'repaired': repaired,
		'errors': errors,
		'remaining': remaining,
	})
