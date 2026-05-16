from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from pathlib import Path

from flask import jsonify, send_file
from sqlalchemy.orm.attributes import flag_modified

from aplicacion import db
from aplicacion.models.proceso4 import Proceso4SceneMedia, Proceso4SubprocessState

from .. import proceso4_bp
from ..helpers import (
	get_or_create_job,
	get_or_create_subprocess_state,
	get_job_dir,
	_build_section_title_metadata,
	ensure_scene_media_local_file,
	ensure_scene_media_proxy_local_file,
)
from ..render_ffmpeg import (
	_build_black_scene,
	_build_single_clip,
	_build_indice_clip,
	_build_pregunta_capciosa_clip,
	_apply_pregunta_text_overlay,
	_build_multi_clip,
	_apply_section_title_overlay,
	_apply_fade_in,
	_file_ok,
)

logger = logging.getLogger(__name__)
_SCENE_PREVIEW_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_SCENE_PREVIEW_LOCKS_GUARD = threading.Lock()


def _get_scene_preview_lock(pid: int, scene_num: int) -> threading.Lock:
	key = (int(pid), int(scene_num))
	with _SCENE_PREVIEW_LOCKS_GUARD:
		lock = _SCENE_PREVIEW_LOCKS.get(key)
		if lock is None:
			lock = threading.Lock()
			_SCENE_PREVIEW_LOCKS[key] = lock
		return lock


def _send_preview_file(path: Path):
	resp = send_file(str(path), mimetype='video/mp4', conditional=True)
	resp.headers['Cache-Control'] = 'private, max-age=0, must-revalidate'
	return resp

# ---------------------------------------------------------------------------
# Scene preview render
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/preview', methods=['GET'])
def preview_scene(pid: int, scene_num: int):
	"""Render and stream a preview MP4 for a single scene.

	This reuses the same clip-building helpers as the final render so the
	frontend preview button can show all assigned clips as one composed scene.
	"""
	get_or_create_job(pid)
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()

	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'Timeline no importado.'}), 404

	scenes = tl.get('scenes', [])
	if not scenes:
		return jsonify({'error': 'Timeline sin escenas.'}), 404

	scene_idx = next(
		(i for i, scene in enumerate(scenes) if int(scene.get('scene_num', 0)) == scene_num),
		None,
	)
	if scene_idx is None:
		return jsonify({'error': f'Escena {scene_num} no encontrada.'}), 404

	scene = scenes[scene_idx]
	media_list = Proceso4SceneMedia.query.filter_by(
		proceso1_job_id=pid,
		scene_num=scene_num,
	).order_by(Proceso4SceneMedia.clip_index).all()
	for media in media_list:
		ensure_scene_media_local_file(media)
		if media.proxy_path:
			ensure_scene_media_proxy_local_file(media)

	_ai_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='auto_indice'
	).first()
	_ai_out = (_ai_state.output_payload or {}) if _ai_state else {}
	_indice_scene_nums_ordered: list[int] = list(_ai_out.get('scene_nums', []))
	_indice_scene_nums_set: set[int] = set(_indice_scene_nums_ordered)
	_first_indice_sn: int | None = _indice_scene_nums_ordered[0] if _indice_scene_nums_ordered else None

	effective_durations: list[float] = []
	for i, sc in enumerate(scenes):
		sc_start = float(sc.get('start', 0.0))
		sc_dur = float(sc.get('duration', 5.0))
		if i + 1 < len(scenes):
			next_start = float(scenes[i + 1].get('start', 0.0))
			gap = round(next_start - (sc_start + sc_dur), 4)
			eff = round(sc_start + sc_dur + max(gap, 0.0) - sc_start, 4)
			eff = max(eff, sc_dur)
		else:
			eff = sc_dur
		effective_durations.append(eff)

	eff_duration = effective_durations[scene_idx]
	_section_title_meta = _build_section_title_metadata(pid, scenes, effective_durations)
	section_title_meta = _section_title_meta.get(int(scene_num))
	indice_block_eff_duration = 0.0
	if _indice_scene_nums_set and scene_num in _indice_scene_nums_set:
		for idx, sc in enumerate(scenes):
			if sc.get('scene_num') in _indice_scene_nums_set:
				indice_block_eff_duration += effective_durations[idx]

	cur_section = scene.get('section', '')
	prev_section = scenes[scene_idx - 1].get('section', '') if scene_idx > 0 else ''
	fade_in_dur = 0.0
	if scene_idx == 0:
		fade_in_dur = 0.4
	elif cur_section != prev_section and cur_section not in ('intro', 'cierre'):
		fade_in_dur = 0.6

	job_dir = get_job_dir(pid)
	work_dir = job_dir / 'output' / 'scene_previews' / f'scene_{scene_num}'
	out_path = work_dir / f'scene_{scene_num}.mp4'
	meta_path = work_dir / 'preview_meta.json'

	signature_payload = {
		'renderer_version': 'scene-preview-section-title-outline-v9',
		'scene': {
			'scene_num': scene_num,
			'start': scene.get('start'),
			'end': scene.get('end'),
			'duration': scene.get('duration'),
			'effective_duration': round(eff_duration, 4),
			'section': scene.get('section'),
		},
		'media': [
			{
				'id': media.id,
				'clip_index': media.clip_index,
				'media_type': media.media_type,
				'file_path': media.file_path,
				'file_mtime': Path(media.file_path).stat().st_mtime if Path(media.file_path).exists() else None,
				'duration': media.duration,
				'trim_start': media.trim_start,
				'trim_end': media.trim_end,
				'speed': media.speed,
				'image_motion_preset': media.image_motion_preset,
				'image_motion_intensity': media.image_motion_intensity,
				'transition_type': media.transition_type,
				'transition_duration': media.transition_duration,
				'text_overlay': media.text_overlay,
				'updated_at': media.updated_at.isoformat() if media.updated_at else None,
			}
			for media in media_list
		],
		'indice': {
			'scene_nums': _indice_scene_nums_ordered,
			'first_scene_num': _first_indice_sn,
			'block_effective_duration': round(indice_block_eff_duration, 4),
		},
		'section_title': section_title_meta,
	}
	signature = hashlib.sha256(
		json.dumps(signature_payload, sort_keys=True, default=str).encode('utf-8')
	).hexdigest()

	if out_path.exists() and meta_path.exists() and _file_ok(str(out_path)):
		try:
			meta = json.loads(meta_path.read_text(encoding='utf-8'))
			if meta.get('signature') == signature:
				logger.info(f"[P4] Scene preview cache hit job={pid} scene={scene_num}")
				return _send_preview_file(out_path)
		except Exception as exc:
			logger.warning(f"[P4] Scene preview cache metadata ignored job={pid} scene={scene_num}: {exc}")

	with _get_scene_preview_lock(pid, scene_num):
		if out_path.exists() and meta_path.exists() and _file_ok(str(out_path)):
			try:
				meta = json.loads(meta_path.read_text(encoding='utf-8'))
				if meta.get('signature') == signature:
					logger.info(f"[P4] Scene preview cache hit after wait job={pid} scene={scene_num}")
					return _send_preview_file(out_path)
			except Exception as exc:
				logger.warning(f"[P4] Scene preview cache metadata ignored job={pid} scene={scene_num}: {exc}")

		shutil.rmtree(work_dir, ignore_errors=True)
		work_dir.mkdir(parents=True, exist_ok=True)

		logger.info(
			f"[P4] Rendering scene preview job={pid} scene={scene_num} "
			f"clips={len(media_list)} effectiveDur={eff_duration:.3f}s"
		)

		try:
			if not media_list:
				clip_path = _build_black_scene(eff_duration, work_dir, scene_num)
			elif len(media_list) == 1:
				clip = media_list[0]
				overlay = clip.text_overlay or {}
				if overlay.get('style') == 'pregunta_capciosa' and overlay.get('lines'):
					pc_text = overlay['lines'][0] if overlay['lines'] else ''
					pc_overlay_start = float(overlay.get('overlay_start', 0.0))
					clip_path = _build_pregunta_capciosa_clip(
						clip,
						eff_duration,
						work_dir,
						scene_num,
						pc_text,
						overlay_start=pc_overlay_start,
					)
				elif overlay.get('style') == 'indice' and overlay.get('lines'):
					if _first_indice_sn is not None and scene_num != _first_indice_sn:
						first_scene = next((sc for sc in scenes if int(sc.get('scene_num', 0)) == _first_indice_sn), None)
						first_media = Proceso4SceneMedia.query.filter_by(
							proceso1_job_id=pid,
							scene_num=_first_indice_sn,
						).order_by(Proceso4SceneMedia.clip_index).all()
						if first_scene and first_media:
							scene_num = _first_indice_sn
							scene = first_scene
							media_list = first_media
							clip = first_media[0]
							overlay = clip.text_overlay or overlay
					clip_path = _build_indice_clip(
						clip,
						indice_block_eff_duration if indice_block_eff_duration > 0 else eff_duration,
						work_dir,
						scene_num,
						overlay['lines'],
						scene_offset_in_indice=0.0,
						total_indice_duration=indice_block_eff_duration if indice_block_eff_duration > 0 else eff_duration,
					)
				else:
					clip_path = _build_single_clip(clip, eff_duration, work_dir, scene_num)
			else:
				clip_path = _build_multi_clip(media_list, eff_duration, work_dir, scene_num)

				pc_overlay = None
				for media in media_list:
					media_overlay = media.text_overlay or {}
					if media_overlay.get('style') == 'pregunta_capciosa' and media_overlay.get('lines'):
						pc_overlay = media_overlay
						break
				if pc_overlay:
					pc_text = pc_overlay['lines'][0] if pc_overlay['lines'] else ''
					pc_overlay_start = float(pc_overlay.get('overlay_start', 0.0))
					clip_path = _apply_pregunta_text_overlay(
						clip_path,
						eff_duration,
						work_dir,
						scene_num,
						pc_text,
						overlay_start=pc_overlay_start,
					)

			if section_title_meta and _file_ok(clip_path):
				clip_path = _apply_section_title_overlay(
					clip_path,
					eff_duration,
					work_dir,
					scene_num,
					section_title_meta['title'],
					overlay_elapsed_before=float(section_title_meta.get('elapsed_before', 0.0)),
					overlay_duration=float(section_title_meta.get('overlay_duration', 3.5)),
				)

			if fade_in_dur > 0 and _file_ok(clip_path):
				_apply_fade_in(clip_path, fade_in_dur, work_dir, scene_num, tag=f'S{scene_num} preview')

			if not _file_ok(clip_path):
				logger.error(f"[P4] Scene preview build failed job={pid} scene={scene_num}")
				return jsonify({'error': 'No se pudo generar el preview de la escena.'}), 500

			meta_path.write_text(json.dumps({
				'signature': signature,
				'created_at': time.time(),
				'duration': eff_duration,
			}, ensure_ascii=False, indent=2), encoding='utf-8')

			return _send_preview_file(Path(clip_path))
		except Exception as exc:
			logger.exception(f"[P4] Scene preview crashed job={pid} scene={scene_num}: {exc}")
			return jsonify({'error': 'Error interno al renderizar el preview de la escena.'}), 500


# ---------------------------------------------------------------------------
# Batch proxy generation for existing media
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/generate-proxies', methods=['POST'])
def generate_proxies(pid: int):
	"""Generate 480p proxy files for all video media that don't have one yet.

	Runs synchronously (blocks until done) so the frontend gets a real count.
	Called once manually from the Timeline monitor header.
	"""
	get_or_create_job(pid)
	records = Proceso4SceneMedia.query.filter_by(
		proceso1_job_id=pid, media_type='video'
	).all()

	total = len(records)
	generated = 0

	for rec in records:
		# Skip if proxy already exists and is valid
		if rec.proxy_path and (Path(rec.proxy_path).exists() or ensure_scene_media_proxy_local_file(rec)):
			continue
		if not Path(rec.file_path).exists() and not ensure_scene_media_local_file(rec):
			continue
		proxy = _generate_proxy(rec.file_path, rec.id)
		if proxy:
			from sqlalchemy.orm.attributes import flag_modified
			rec.proxy_path = proxy
			flag_modified(rec, 'proxy_path')
			generated += 1

	db.session.commit()
	logger.info(f"[P4] generate-proxies job={pid}: {generated}/{total} generated")
	return jsonify({'generated': generated, 'total': total})
