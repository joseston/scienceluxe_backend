from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import shutil
import uuid
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from aplicacion import db
from aplicacion.models.proceso4 import Proceso4SceneMedia, Proceso4SubprocessState
from aplicacion.models.clip_library import ClipLibraryItem

from .. import proceso4_bp
from ..ffmpeg_setup import FFPROBE_BIN
from ..helpers import (
	get_or_create_job,
	_get_scene_effective_duration,
	_get_scene_duration,
	_effective_clip_duration,
	_get_video_duration,
	_generate_proxy_async,
	ensure_scene_media_local_file,
	ensure_scene_media_proxy_local_file,
)
from ..render_ffmpeg import (
	_normalize_image_motion_preset,
	_normalize_image_motion_intensity,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Media Upload per Scene
# ---------------------------------------------------------------------------

def _get_scene_p3_metadata(pid: int, scene_num: int) -> dict:
	"""Get visual_description, visual_type, physical_composition from P3 timeline."""
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='import_timeline'
	).first()
	if not import_state:
		return {}
	tl = (import_state.output_payload or {}).get('timeline', {})
	for s in tl.get('scenes', []):
		if s.get('scene_num') == scene_num:
			return {
				'visual_description': s.get('visual_description', ''),
				'visual_type': s.get('visual_type', ''),
				'physical_composition': s.get('physical_composition', ''),
			}
	return {}


@proceso4_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media', methods=['POST'])
def upload_scene_media(pid: int, scene_num: int):
	"""Upload a video or image for a specific scene.

	The file is saved once in the central clip library (content-addressed by
	SHA-256).  The Proceso4SceneMedia record points directly to the library
	file — NO local copy is made, avoiding double disk usage.

	For videos: detects original duration via ffprobe, sets trim_end = detected.
	For images: calculates remaining scene time (scene_duration - already_covered),
	            sets duration = remaining (min 2s), so the image fills the gap.
	"""
	import hashlib
	from flask import current_app
	from aplicacion.models.clip_library import ClipLibraryItem

	get_or_create_job(pid)

	if 'file' not in request.files:
		return jsonify({'error': 'No file in request.'}), 400

	f = request.files['file']
	if not f.filename:
		return jsonify({'error': 'Empty filename.'}), 400

	# Determine media type
	ext = (f.filename.rsplit('.', 1)[-1] if '.' in f.filename else '').lower()
	video_exts = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
	image_exts = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}

	if ext in video_exts:
		media_type = 'video'
	elif ext in image_exts:
		media_type = 'image'
	else:
		return jsonify({'error': f'Extensión no soportada: .{ext}'}), 400

	# Determine clip_index (next available)
	existing_clips = Proceso4SceneMedia.query.filter_by(
		proceso1_job_id=pid, scene_num=scene_num
	).order_by(Proceso4SceneMedia.clip_index).all()
	# Use max existing index + 1 instead of len(), so gaps left by deletions don't cause collisions
	clip_index = (max(ec.clip_index for ec in existing_clips) + 1) if existing_clips else 0

	# Calculate already-covered time by existing clips
	already_covered = 0.0
	for ec in existing_clips:
		already_covered += _effective_clip_duration(ec)

	# Get scene effective duration (includes absorbed gaps) for proper auto-sizing
	scene_duration = _get_scene_effective_duration(pid, scene_num) or _get_scene_duration(pid, scene_num)
	remaining = max(0, scene_duration - already_covered) if scene_duration else 5.0

	# ── Save to clip library (content-addressed) ──────────────────────
	clips_dir = Path(current_app.config['CLIPS_LIBRARY_DIR'])
	clips_dir.mkdir(parents=True, exist_ok=True)

	# Save to temp, compute SHA-256
	tmp_dir = clips_dir / '_tmp'
	tmp_dir.mkdir(parents=True, exist_ok=True)
	tmp_path = tmp_dir / f"{uuid.uuid4().hex}.{ext}"
	f.save(str(tmp_path))

	file_hash = hashlib.sha256()
	with open(tmp_path, 'rb') as fh:
		for chunk in iter(lambda: fh.read(1 << 20), b''):
			file_hash.update(chunk)
	file_hash = file_hash.hexdigest()

	# Check if clip already exists in library (dedup)
	library_clip = ClipLibraryItem.query.filter_by(file_hash=file_hash).first()

	if library_clip:
		# File already in library — remove temp, reuse existing
		tmp_path.unlink(missing_ok=True)
		out_path = library_clip.file_path
	else:
		# Move to content-addressed location: originals/<hash[:2]>/<hash>.<ext>
		sub = file_hash[:2]
		dest_dir = clips_dir / 'originals' / sub
		dest_dir.mkdir(parents=True, exist_ok=True)
		dest_path = dest_dir / f"{file_hash}.{ext}"
		shutil.move(str(tmp_path), str(dest_path))
		out_path = str(dest_path)
		file_size = dest_path.stat().st_size

		# Detect metadata
		vid_dur = None
		res_w, res_h = None, None
		if media_type == 'video':
			vid_dur = _get_video_duration(out_path)
			try:
				result = subprocess.run(
					[FFPROBE_BIN, '-v', 'quiet', '-print_format', 'json', '-show_streams', out_path],
					capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
				)
				if result.returncode == 0 and result.stdout:
					info = json.loads(result.stdout)
					for s in info.get('streams', []):
						if s.get('codec_type') == 'video':
							res_w, res_h = s.get('width'), s.get('height')
							break
			except Exception:
				pass

		# Get P3 scene metadata for auto-tagging
		p3_meta = _get_scene_p3_metadata(pid, scene_num)

		library_clip = ClipLibraryItem(
			file_hash=file_hash,
			original_filename=f.filename,
			file_path=out_path,
			media_type=media_type,
			duration=vid_dur,
			resolution_w=res_w,
			resolution_h=res_h,
			file_size_bytes=file_size,
			visual_type=p3_meta.get('visual_type') or None,
			visual_description=p3_meta.get('visual_description') or None,
			physical_composition=p3_meta.get('physical_composition') or None,
			keywords=[],
			tags=[],
			source_type='scene_upload',
			source_info={'proceso1_job_id': pid, 'scene_num': scene_num},
		)
		db.session.add(library_clip)
		db.session.flush()  # get library_clip.id

		# Generate thumbnail, proxy, embedding in background
		from aplicacion.endpoints.clip_library import (
			_generate_assets_async as _lib_generate_assets,
			_sync_clip_library_file_async as _lib_sync_clip_file_async,
		)
		_lib_sync_clip_file_async(dest_path, current_app._get_current_object(), reason='scene-upload')
		_lib_generate_assets(library_clip.id, out_path, current_app._get_current_object())

	# ── file_path for Proceso4SceneMedia points to library file ───────
	# Get duration for videos
	if media_type == 'video':
		detected_dur = library_clip.duration or _get_video_duration(out_path) or 5.0
		duration = detected_dur
		trim_end = detected_dur
	else:
		# Image: display for the remaining time, min 2s
		img_dur = max(2.0, remaining) if remaining > 0 else 5.0
		duration = img_dur
		trim_end = img_dur

	# Create DB record — file_path points to library, no local copy
	record = Proceso4SceneMedia(
		proceso1_job_id=pid,
		scene_num=scene_num,
		clip_index=clip_index,
		media_type=media_type,
		original_filename=f.filename,
		file_path=out_path,
		duration=duration,
		trim_start=0.0,
		trim_end=trim_end,
		transition_type='cut',
		transition_duration=0.0,
		library_clip_id=library_clip.id,
	)
	db.session.add(record)
	db.session.commit()

	logger.info(f"[P4] job={pid} scene={scene_num} clip={clip_index} type={media_type} "
				f"file={f.filename} library_clip={library_clip.id} hash={file_hash[:12]}.. "
				f"effectiveDur={_effective_clip_duration(record):.1f}s "
				f"sceneRemaining={remaining:.1f}s")

	# Generate low-res proxy for scene preview (uses library proxy if available)
	if media_type == 'video' and library_clip.proxy_path:
		record.proxy_path = library_clip.proxy_path
		db.session.commit()
	elif media_type == 'video':
		_generate_proxy_async(out_path, record.id, current_app._get_current_object())

	return jsonify(record.to_dict()), 201


@proceso4_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media', methods=['GET'])
def list_scene_media(pid: int, scene_num: int):
	"""List all media for a scene."""
	get_or_create_job(pid)
	media = Proceso4SceneMedia.query.filter_by(
		proceso1_job_id=pid, scene_num=scene_num
	).order_by(Proceso4SceneMedia.clip_index).all()
	db.session.commit()
	return jsonify([m.to_dict() for m in media])


@proceso4_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media/<int:media_id>', methods=['PUT'])
def update_scene_media(pid: int, scene_num: int, media_id: int):
	"""Update editing parameters for a media clip."""
	get_or_create_job(pid)
	record = Proceso4SceneMedia.query.get_or_404(media_id)
	if record.proceso1_job_id != pid or record.scene_num != scene_num:
		return jsonify({'error': 'Media not found for this scene.'}), 404

	body = request.get_json(force=True) or {}

	if 'trimStart' in body:
		record.trim_start = float(body['trimStart'])
	
	if 'trimEnd' in body:
		new_trim_end = float(body['trimEnd']) if body['trimEnd'] is not None else None
		# Validate: For videos, trim_end cannot exceed the video's actual duration
		if new_trim_end is not None and record.media_type == 'video':
			if record.duration and new_trim_end > record.duration:
				return jsonify({
					'error': f'trim_end ({new_trim_end}s) no puede exceder la duración del video ({record.duration}s)'
				}), 400
		record.trim_end = new_trim_end
	
	if 'transitionType' in body:
		record.transition_type = str(body['transitionType'])
		if record.transition_type == 'cut':
			record.transition_duration = 0.0
		elif 'transitionDuration' not in body and (record.transition_duration or 0.0) <= 0.0:
			record.transition_duration = 0.5
	if 'transitionDuration' in body:
		record.transition_duration = float(body['transitionDuration'])
	if 'speed' in body:
		new_speed = float(body['speed'])
		if new_speed < 0.25 or new_speed > 4.0:
			return jsonify({'error': f'Speed ({new_speed}) must be between 0.25 and 4.0'}), 400
		record.speed = new_speed
	if 'imageMotionPreset' in body or 'imageMotionIntensity' in body:
		if record.media_type != 'image':
			return jsonify({'error': 'imageMotionPreset/imageMotionIntensity only apply to image clips.'}), 400
		if 'imageMotionPreset' in body:
			record.image_motion_preset = _normalize_image_motion_preset(body.get('imageMotionPreset'))
		if 'imageMotionIntensity' in body:
			record.image_motion_intensity = _normalize_image_motion_intensity(body.get('imageMotionIntensity'))
	# For images: allow setting display duration directly
	if 'displayDuration' in body and record.media_type == 'image':
		dur = float(body['displayDuration'])
		record.trim_start = 0.0
		record.trim_end = max(0.5, dur)
		record.duration = record.trim_end

	db.session.commit()
	return jsonify(record.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media/<int:media_id>', methods=['DELETE'])
def delete_scene_media(pid: int, scene_num: int, media_id: int):
	"""Delete a media clip from a scene."""
	get_or_create_job(pid)
	record = Proceso4SceneMedia.query.get_or_404(media_id)
	if record.proceso1_job_id != pid or record.scene_num != scene_num:
		return jsonify({'error': 'Media not found for this scene.'}), 404

	# Only delete the physical file if it's NOT a library clip.
	# Library clips live in the central library — we just remove the reference.
	if not record.library_clip_id:
		try:
			file_path = Path(record.file_path)
			if file_path.exists():
				file_path.unlink()
		except Exception as e:
			logger.warning(f"Could not delete file {record.file_path}: {e}")
		try:
			if record.proxy_path:
				proxy_p = Path(record.proxy_path)
				if proxy_p.exists():
					proxy_p.unlink()
		except Exception as e:
			logger.warning(f"Could not delete proxy {record.proxy_path}: {e}")

	db.session.delete(record)
	db.session.commit()
	return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Serve uploaded media files (for preview)
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/media-file/<int:media_id>', methods=['GET'])
def serve_media_file(pid: int, media_id: int):
	"""Serve an uploaded media file for frontend preview."""
	record = Proceso4SceneMedia.query.get_or_404(media_id)
	if record.proceso1_job_id != pid:
		return jsonify({'error': 'Not found'}), 404
	path = Path(record.file_path)
	if not path.exists() and not ensure_scene_media_local_file(record):
		return jsonify({'error': 'File not found on disk'}), 404

	# Determine mimetype
	ext = path.suffix.lower()
	mime_map = {
		'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.avi': 'video/x-msvideo',
		'.mkv': 'video/x-matroska', '.webm': 'video/webm',
		'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
		'.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
	}
	mimetype = mime_map.get(ext, 'application/octet-stream')
	return send_file(str(path), mimetype=mimetype, conditional=True)


@proceso4_bp.route('/jobs/<int:pid>/media-file/<int:media_id>/proxy', methods=['GET'])
def serve_media_proxy(pid: int, media_id: int):
	"""Serve the low-res proxy for a media file (for timeline preview).

	Falls back to the original file if proxy is not yet available.
	"""
	record = Proceso4SceneMedia.query.get_or_404(media_id)
	if record.proceso1_job_id != pid:
		return jsonify({'error': 'Not found'}), 404

	# Try proxy first
	if record.proxy_path:
		proxy_p = Path(record.proxy_path)
		if proxy_p.exists() or ensure_scene_media_proxy_local_file(record):
			return send_file(str(proxy_p), mimetype='video/mp4', conditional=True)

	# Fallback to original
	path = Path(record.file_path)
	if not path.exists() and not ensure_scene_media_local_file(record):
		return jsonify({'error': 'File not found on disk'}), 404
	ext = path.suffix.lower()
	mime_map = {
		'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.avi': 'video/x-msvideo',
		'.mkv': 'video/x-matroska', '.webm': 'video/webm',
	}
	return send_file(str(path), mimetype=mime_map.get(ext, 'video/mp4'), conditional=True)
