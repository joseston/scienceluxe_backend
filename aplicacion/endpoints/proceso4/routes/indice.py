from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import jsonify, request
from sqlalchemy.orm.attributes import flag_modified

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job
from aplicacion.models.proceso2 import Proceso2SubprocessState
from aplicacion.models.proceso4 import (
	Proceso4AudioTrack,
	Proceso4GlobalAsset,
	Proceso4SceneMedia,
	Proceso4SubprocessState,
)

from .. import proceso4_bp
from ..helpers import (
	get_or_create_job,
	get_or_create_subprocess_state,
	_save_state,
	_get_indice_data,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pregunta retórica helpers
# ---------------------------------------------------------------------------

import re as _re


def _extract_rhetorical_question(full_text: str) -> str | None:
	"""Return the last sentence ending with '?' from *full_text*, or None."""
	if not full_text or '?' not in full_text:
		return None
	# Split on sentence-ending punctuation but keep the delimiter
	sentences = _re.split(r'(?<=[.!?])\s+', full_text.strip())
	# Walk backwards to find last sentence with '?'
	for sent in reversed(sentences):
		if '?' in sent:
			return sent.strip()
	return None


def _flatten_segment_words_inline(segments_json: list[dict]) -> list[dict]:
	"""Flatten word-level timestamps from whisper segments into one stream."""
	out: list[dict] = []
	for seg in segments_json:
		words = seg.get('words') or []
		if words:
			out.extend(words)
		else:
			text = (seg.get('text') or '').strip()
			if text:
				out.append({'word': text, 'start': seg['start'], 'end': seg['end']})
	return out


def _compute_overlay_start_from_words(
	pid: int, overlay_text: str, scene_abs_start: float, scene_duration: float,
) -> float:
	"""Compute the offset (relative to scene start) where *overlay_text* begins being narrated.

	Uses word-level timestamps from the *_segments.json* produced by Proceso 2.
	Returns 0.0 if timestamps are unavailable or the text cannot be matched.
	"""
	try:
		srt_state = Proceso2SubprocessState.query.filter_by(
			proceso1_job_id=pid, subprocess_key='srt',
		).first()
		if not srt_state:
			return 0.0
		srt_path_value = (srt_state.output_payload or {}).get('srtPath')
		if not srt_path_value:
			return 0.0
		segments_json_path = Path(str(srt_path_value).replace('.srt', '_segments.json'))
		if not segments_json_path.exists():
			return 0.0
		raw_segments = json.loads(segments_json_path.read_text(encoding='utf-8'))
		all_words = _flatten_segment_words_inline(raw_segments)
		if not all_words:
			return 0.0
	except Exception as exc:
		logger.warning(f'[P4] _compute_overlay_start: Could not load word timestamps: {exc}')
		return 0.0

	# Filter words within this scene's time window (with small tolerance)
	scene_end = scene_abs_start + scene_duration
	scene_words = [
		w for w in all_words
		if float(w.get('start', 0)) >= scene_abs_start - 0.05
		and float(w.get('end', 0)) <= scene_end + 0.5
	]
	if not scene_words:
		return 0.0

	# Normalise overlay text for matching: lowercase, strip punctuation
	def _norm(t: str) -> str:
		return _re.sub(r'[^\w\s]', '', t.lower()).strip()

	target_words = _norm(overlay_text).split()
	if not target_words:
		return 0.0

	# Sliding window over scene_words to find best match for target_words[0..N]
	first_target = target_words[0]
	for i, w in enumerate(scene_words):
		word_text = _norm(w.get('word', ''))
		if word_text == first_target:
			# Check if subsequent words match
			match = True
			check_len = min(len(target_words), len(scene_words) - i, 5)  # check up to 5 words
			for j in range(1, check_len):
				if _norm(scene_words[i + j].get('word', '')) != target_words[j]:
					match = False
					break
			if match:
				abs_start = float(w.get('start', scene_abs_start))
				offset = max(0.0, abs_start - scene_abs_start)
				logger.info(
					f'[P4] overlay_start computed: word "{w.get("word")}" at '
					f'{abs_start:.3f}s → offset {offset:.3f}s within scene'
				)
				return round(offset, 3)

	logger.info('[P4] overlay_start: could not match question words in SRT, defaulting to 0.0')
	return 0.0


def _merge_saved_pregunta_capciosa(existing_pc: dict | None, detected_pc: dict | None) -> dict | None:
	"""Preserve manually saved pregunta-capciosa edits across auto-indice recalculation."""
	if not detected_pc:
		return None
	if not existing_pc:
		return detected_pc
	if existing_pc.get('scene_num') != detected_pc.get('scene_num'):
		return detected_pc

	merged = dict(detected_pc)

	if existing_pc.get('overlay_text_customized'):
		saved_text = str(existing_pc.get('overlay_text') or '').strip()
		if saved_text:
			merged['overlay_text'] = saved_text
			merged['overlay_text_customized'] = True

	if existing_pc.get('overlay_start_customized'):
		try:
			merged['overlay_start'] = round(max(0.0, float(existing_pc.get('overlay_start', 0.0))), 3)
			merged['overlay_start_customized'] = True
		except (TypeError, ValueError):
			pass

	return merged


def _build_indice_text(subtemas: list[str]) -> str:
	"""Build the human-readable indice narration text from the subtema list."""
	cleaned = [str(item).strip() for item in (subtemas or []) if str(item).strip()]
	if not cleaned:
		return ''
	if len(cleaned) == 1:
		return 'In this video: ' + cleaned[0]
	return 'In this video: ' + ', '.join(cleaned[:-1]) + ' and ' + cleaned[-1]


# ---------------------------------------------------------------------------
# ÍNDICE auto-generation endpoint
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/auto-indice', methods=['POST'])
def auto_indice(pid: int):
	"""Auto-detect ÍNDICE scenes and assign the global image + music to them.

	Scans the imported P3 timeline for intro scenes whose text begins with
	'en este video' and assigns:
	  - Proceso4SceneMedia (clip_index=0) with the global indice_image
	  - Proceso4AudioTrack (track_type='indice_music') starting at the first ÍNDICE scene
	  - text_overlay with the subtema titles for FFmpeg drawtext
	"""
	Proceso1Job.query.get_or_404(pid)

	# Ensure global assets are configured
	indice_image_asset = Proceso4GlobalAsset.query.filter_by(asset_key='indice_image').first()

	if not indice_image_asset:
		return jsonify({
			'error': 'Falta el activo global indice_image. '
			         'Súbelo primero en la sección Configuración.',
		}), 400

	# Load timeline
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='import_timeline'
	).first()
	if not import_state or import_state.status != 'completed':
		return jsonify({'error': 'Timeline no importado todavía. Carga el proyecto primero.'}), 400

	existing_auto_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='auto_indice'
	).first()
	existing_pc = None
	if existing_auto_state and existing_auto_state.output_payload:
		existing_pc = (existing_auto_state.output_payload or {}).get('pregunta_capciosa')

	timeline = (import_state.output_payload or {}).get('timeline', {})
	scenes = timeline.get('scenes', [])

	# Find ÍNDICE scenes: all intro scenes from the first one whose text
	# starts with "Today" / "En este video" until the end of the intro section.
	# This covers 1, 2, or 3 scenes that form the índice block.
	intro_scenes = [s for s in scenes if s.get('section') == 'intro']
	if not intro_scenes:
		return jsonify({
			'error': 'No se encontraron escenas de introducción en el timeline.',
		}), 400

	# Locate the first intro scene whose text begins with "Today" or "En este video"
	indice_start_idx = None
	for idx, sc in enumerate(intro_scenes):
		txt = (sc.get('text') or '').strip().lower()
		if txt.startswith('today') or txt.startswith('en este video'):
			indice_start_idx = idx
			break

	if indice_start_idx is None:
		# Fallback: use the last intro scene (legacy behaviour)
		indice_scenes = [intro_scenes[-1]]
	else:
		# All intro scenes from the detected start to the end of intro
		indice_scenes = intro_scenes[indice_start_idx:]

	# Get subtemas for text overlay (resolved from P1 DB → session JSON → empty)
	indice_data = _get_indice_data(pid)
	detected_subtemas = indice_data['subtemas']
	subtemas = detected_subtemas
	indice_text = indice_data['indice_text']
	existing_auto_output = (existing_auto_state.output_payload or {}) if existing_auto_state else {}
	subtemas_customized = bool(existing_auto_output.get('subtemas_customized'))
	indice_text_customized = bool(existing_auto_output.get('indice_text_customized'))
	if subtemas_customized:
		saved_subtemas = [str(item).strip() for item in (existing_auto_output.get('subtemas') or []) if str(item).strip()]
		if saved_subtemas:
			subtemas = saved_subtemas
			indice_text = _build_indice_text(saved_subtemas)
	if indice_text_customized:
		saved_indice_text = str(existing_auto_output.get('indice_text') or '').strip()
		if saved_indice_text:
			indice_text = saved_indice_text

	overlay = {'lines': subtemas, 'style': 'indice'} if subtemas else None

	first_scene = indice_scenes[0]
	indice_scene_nums = [s['scene_num'] for s in indice_scenes]
	total_indice_duration = sum(float(s.get('duration', 0)) for s in indice_scenes)
	start_time = float(first_scene.get('start', 0))

	# Upsert SceneMedia clip_index=0 for each ÍNDICE scene
	for scene in indice_scenes:
		sn = scene['scene_num']
		scene_dur = float(scene.get('duration', 5.0))
		existing_clip = Proceso4SceneMedia.query.filter_by(
			proceso1_job_id=pid, scene_num=sn, clip_index=0
		).first()
		if existing_clip:
			existing_clip.media_type = 'image'
			existing_clip.original_filename = indice_image_asset.original_filename
			existing_clip.file_path = indice_image_asset.file_path
			existing_clip.duration = scene_dur
			existing_clip.trim_start = 0.0
			existing_clip.trim_end = scene_dur
			existing_clip.text_overlay = overlay
		else:
			clip = Proceso4SceneMedia(
				proceso1_job_id=pid,
				scene_num=sn,
				clip_index=0,
				media_type='image',
				original_filename=indice_image_asset.original_filename,
				file_path=indice_image_asset.file_path,
				duration=scene_dur,
				trim_start=0.0,
				trim_end=scene_dur,
				text_overlay=overlay,
			)
			db.session.add(clip)

	# ── Pregunta capciosa: the intro scene immediately BEFORE the índice block ──
	pregunta_capciosa_payload: dict | None = None
	# Find the index of the first índice scene within intro_scenes
	_first_indice_sn = indice_scenes[0]['scene_num']
	_first_indice_idx = next((i for i, s in enumerate(intro_scenes) if s['scene_num'] == _first_indice_sn), 0)
	if _first_indice_idx >= 1:
		pc_scene = intro_scenes[_first_indice_idx - 1]
		pc_sn = pc_scene['scene_num']
		pc_text = pc_scene.get('text', '')
		pc_start = float(pc_scene.get('start', 0))
		pc_dur = float(pc_scene.get('duration', 5.0))

		# ── Extract only the rhetorical question (last sentence ending with '?') ──
		overlay_text = pc_text  # fallback: full text
		overlay_start = 0.0     # fallback: start of scene
		_question = _extract_rhetorical_question(pc_text)
		if _question:
			overlay_text = _question
		# ── Try to compute overlay_start from word-level SRT timestamps ──
		overlay_start = _compute_overlay_start_from_words(pid, overlay_text, pc_start, pc_dur)

		pc_overlay = {
			'lines': [overlay_text],
			'style': 'pregunta_capciosa',
			'overlay_start': overlay_start,
		}

		# Upsert text_overlay on the existing SceneMedia (if any) for that scene
		existing_pc_clip = Proceso4SceneMedia.query.filter_by(
			proceso1_job_id=pid, scene_num=pc_sn, clip_index=0
		).first()
		if existing_pc_clip:
			existing_pc_clip.text_overlay = pc_overlay

		pregunta_capciosa_payload = {
			'scene_num': pc_sn,
			'text': pc_text,
			'start': pc_start,
			'duration': pc_dur,
			'overlay_text': overlay_text,
			'overlay_start': overlay_start,
		}
		pregunta_capciosa_payload = _merge_saved_pregunta_capciosa(existing_pc, pregunta_capciosa_payload)
		pc_overlay = {
			'lines': [pregunta_capciosa_payload.get('overlay_text') or pc_text],
			'style': 'pregunta_capciosa',
			'overlay_start': pregunta_capciosa_payload.get('overlay_start', 0.0),
		}
		if existing_pc_clip:
			existing_pc_clip.text_overlay = pc_overlay
		logger.info(
			f'[P4] Pregunta capciosa detected → scene {pc_sn}: '
			f'overlay_text="{overlay_text[:60]}…" overlay_start={overlay_start:.2f}s'
		)

	# Clean up any legacy indice_music audio tracks (feature removed)
	old_tracks = Proceso4AudioTrack.query.filter_by(
		proceso1_job_id=pid, track_type='indice_music'
	).all()
	for t in old_tracks:
		db.session.delete(t)

	# Save subprocess state
	auto_state = get_or_create_subprocess_state(pid, 'auto_indice')
	_save_state(auto_state, {
		'status': 'completed',
		'output': {
			'scene_nums': indice_scene_nums,
			'indice_text': indice_text,
			'subtemas': subtemas,
			'subtemas_customized': subtemas_customized,
			'indice_text_customized': indice_text_customized,
			'start': start_time,
			'total_duration': round(total_indice_duration, 3),
			'pregunta_capciosa': pregunta_capciosa_payload,
		},
	})
	db.session.commit()

	return jsonify({
		'status': 'completed',
		'sceneNums': indice_scene_nums,
		'start': start_time,
		'totalDuration': round(total_indice_duration, 3),
		'subtemas': subtemas,
		'indiceText': indice_text,
		'preguntaCapciosa': pregunta_capciosa_payload,
	})


# ---------------------------------------------------------------------------
# PATCH — Pregunta Retórica (editar overlay_text / overlay_start)
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/pregunta-capciosa', methods=['PATCH'])
def patch_pregunta_capciosa(pid: int):
	"""Update the overlay_text and/or overlay_start of the pregunta capciosa.

	Accepts JSON body:
	  { "overlay_text": "...", "overlay_start": 1.23 }
	Both fields are optional; only provided fields are updated.
	"""
	Proceso1Job.query.get_or_404(pid)
	body = request.get_json(silent=True) or {}

	auto_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='auto_indice',
	).first()
	if not auto_state or not auto_state.output_payload:
		return jsonify({'error': 'auto_indice no ejecutado todavía'}), 404

	pc = auto_state.output_payload.get('pregunta_capciosa')
	if not pc:
		return jsonify({'error': 'No se detectó pregunta retórica en este proyecto'}), 404

	changed = False
	if 'overlay_text' in body:
		new_text = str(body['overlay_text']).strip()
		if new_text:
			pc['overlay_text'] = new_text
			pc['overlay_text_customized'] = True
			changed = True
	if 'overlay_start' in body:
		try:
			new_start = max(0.0, float(body['overlay_start']))
		except (TypeError, ValueError):
			return jsonify({'error': 'overlay_start debe ser un número'}), 400
		pc['overlay_start'] = round(new_start, 3)
		pc['overlay_start_customized'] = True
		changed = True

	if not changed:
		return jsonify({'error': 'Nada que actualizar (envía overlay_text y/o overlay_start)'}), 400

	# Persist to subprocess state (must reassign dict for SQLAlchemy JSON mutation)
	out = dict(auto_state.output_payload)
	out['pregunta_capciosa'] = pc
	auto_state.output_payload = out
	from sqlalchemy.orm.attributes import flag_modified
	flag_modified(auto_state, 'output_payload')

	# Also update SceneMedia text_overlay for the clip
	scene_num = pc.get('scene_num')
	if scene_num is not None:
		clip = Proceso4SceneMedia.query.filter_by(
			proceso1_job_id=pid, scene_num=scene_num, clip_index=0,
		).first()
		if clip:
			ov = dict(clip.text_overlay or {})
			ov['style'] = 'pregunta_capciosa'
			ov['lines'] = [pc.get('overlay_text', pc.get('text', ''))]
			ov['overlay_start'] = pc.get('overlay_start', 0.0)
			clip.text_overlay = ov
			flag_modified(clip, 'text_overlay')

	db.session.commit()

	return jsonify({
		'ok': True,
		'preguntaCapciosa': pc,
	})


@proceso4_bp.route('/jobs/<int:pid>/indice-subtemas', methods=['PATCH'])
def patch_indice_subtemas(pid: int):
	"""Update the indice overlay text lines so timeline and final render stay in sync."""
	Proceso1Job.query.get_or_404(pid)
	body = request.get_json(silent=True) or {}

	auto_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='auto_indice',
	).first()
	if not auto_state or not auto_state.output_payload:
		return jsonify({'error': 'auto_indice no ejecutado todavÃ­a'}), 404

	raw_subtemas = body.get('subtemas')
	if not isinstance(raw_subtemas, list):
		return jsonify({'error': 'subtemas debe ser una lista'}), 400

	subtemas = [str(item).strip() for item in raw_subtemas if str(item).strip()]
	if not subtemas:
		return jsonify({'error': 'Debes enviar al menos un subtema no vacÃ­o'}), 400

	indice_text = _build_indice_text(subtemas)

	out = dict(auto_state.output_payload or {})
	out['subtemas'] = subtemas
	out['indice_text'] = indice_text
	out['subtemas_customized'] = True
	out['indice_text_customized'] = True
	auto_state.output_payload = out
	flag_modified(auto_state, 'output_payload')

	for scene_num in out.get('scene_nums', []) or []:
		clip = Proceso4SceneMedia.query.filter_by(
			proceso1_job_id=pid, scene_num=scene_num, clip_index=0,
		).first()
		if not clip:
			continue
		overlay = dict(clip.text_overlay or {})
		overlay['style'] = 'indice'
		overlay['lines'] = subtemas
		clip.text_overlay = overlay
		flag_modified(clip, 'text_overlay')

	db.session.commit()

	return jsonify({
		'ok': True,
		'subtemas': subtemas,
		'indiceText': indice_text,
	})
