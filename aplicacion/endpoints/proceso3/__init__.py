from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app, send_file, make_response
from pathlib import Path
import hashlib
import json
import logging
import re
import sys
import time

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1SubprocessState
from aplicacion.models.proceso2 import Proceso2SubprocessState
from aplicacion.models.proceso3 import Proceso3Job, Proceso3SubprocessState


proceso3_bp = Blueprint('proceso3', __name__)


logger = logging.getLogger(__name__)

_GEMINI_CALL_SEQUENCE = 0





def get_workspace_data_dir() -> Path:
	return Path(__file__).resolve().parents[4] / 'data'


def get_job_dir(proceso1_job_id: int) -> Path:
	return get_workspace_data_dir() / 'proceso3' / str(proceso1_job_id)


def get_or_create_job(proceso1_job_id: int) -> Proceso3Job:
	Proceso1Job.query.get_or_404(proceso1_job_id)
	job = Proceso3Job.query.get(proceso1_job_id)
	if job is None:
		job = Proceso3Job(proceso1_job_id=proceso1_job_id)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(proceso1_job_id: int, subprocess_key: str) -> Proceso3SubprocessState:
	state = Proceso3SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso3SubprocessState(proceso1_job_id=proceso1_job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state


def _save_state(state: Proceso3SubprocessState, payload: dict) -> Proceso3SubprocessState:
	if 'status' in payload and payload['status'] is not None:
		state.status = str(payload['status'])
	if 'input' in payload and payload['input'] is not None:
		state.input_payload = payload['input']
	if 'output' in payload and payload['output'] is not None:
		state.output_payload = payload['output']
	if 'metadata' in payload and payload['metadata'] is not None:
		state.metadata_payload = payload['metadata']
	db.session.commit()
	return state


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/init', methods=['POST'])
def init_proceso3_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	job_dir = get_job_dir(proceso1_job_id)
	(job_dir / 'input').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso3_bp.route('/jobs/<int:proceso1_job_id>', methods=['GET'])
def get_proceso3_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['GET'])
def get_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	db.session.commit()
	return jsonify(state.to_dict())


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses', methods=['GET'])
def list_subprocess_states(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	states = (
		Proceso3SubprocessState.query
		.filter_by(proceso1_job_id=proceso1_job_id)
		.order_by(Proceso3SubprocessState.updated_at.asc())
		.all()
	)
	return jsonify([s.to_dict() for s in states])


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['PUT'])
def save_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	payload = request.get_json(silent=True) or {}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline (replica legacy):
#   Proceso2 concat (markers.json) + Proceso2 srt (final.srt/_segments.json) ->
#   Proceso3 segment (subtítulos nivel-oración por sección) ->
#   Proceso3 enrich-section (Gemini agrupa en escenas + asigna visuales) ->
#   Proceso3 timeline (combina todos los batches)
#
# Keys in Proceso3SubprocessState:
#   - segment
#   - batch_<seccion>
#   - timeline
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_section(label: str) -> str:
	normalized = (label or '').strip().lower()
	# Only 'parte4_cierre' (legacy label used when parte4 WAS the closing section)
	# should be folded into 'cierre'. 'parte4' by itself is a real independent part
	# and must NOT be merged — videos can have 4 full parts + a separate cierre.
	if normalized in {'parte4_cierre'}:
		return 'cierre'
	return normalized


# ─── Sentence-level subtitle extraction from word-level timestamps ───────


def _is_sentence_end(word_text: str) -> bool:
	"""Return True if the word ends a sentence (. ? !)."""
	text = word_text.strip()
	if not text:
		return False
	if text[-1] in '?!':
		return True
	if text[-1] != '.':
		return False
	# Exclude decimals / thousands separators like "3.14" or "50.000"
	core = text.rstrip('.')
	if core and '.' in core:
		cleaned = core.replace('.', '')
		if cleaned.isdigit():
			return False
	return True


def _flatten_segment_words(segments_json: list[dict]) -> list[dict]:
	"""Flatten word-level timestamps from all whisper segments into one stream."""
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


def _build_subtitle_text(word_group: list[dict]) -> str:
	"""Join words into readable text, fixing whisper splits like '50' + '.000' → '50.000'."""
	parts: list[str] = []
	for w in word_group:
		word = w.get('word', '').strip()
		if not word:
			continue
		if parts and word[0] in '.,;:!?':
			parts[-1] += word
		else:
			parts.append(word)
	return ' '.join(parts)


def _extract_sentence_subtitles(
	section_label: str,
	section_start: float,
	section_end: float,
	all_words: list[dict],
	start_num: int,
) -> tuple[list[dict], int]:
	"""Extract clean sentence-level subtitles from word-level timestamps.

	Only splits at sentence boundaries (. ? !).
	Does NOT merge or group — that's Gemini's job.
	Returns subtitles (not scenes): each subtitle = 1 sentence from the narration.
	"""
	words = [
		w for w in all_words
		if float(w.get('start', 0)) >= section_start - 0.3
		and float(w.get('start', 0)) < section_end + 0.3
	]
	if not words:
		return [], start_num

	# Split words into sentences at . ? !
	sentences: list[list[dict]] = []
	buf: list[dict] = []
	for w in words:
		buf.append(w)
		if _is_sentence_end(w.get('word', '')):
			sentences.append(buf)
			buf = []
	if buf:
		sentences.append(buf)

	subtitles: list[dict] = []
	num = start_num
	for group in sentences:
		if not group:
			continue
		text = _build_subtitle_text(group)
		if not text:
			continue
		subtitles.append({
			'num': num,
			'section': section_label,
			'start': round(float(group[0]['start']), 3),
			'end': round(float(group[-1]['end']), 3),
			'text': text,
			'duration': round(float(group[-1]['end']) - float(group[0]['start']), 2),
		})
		num += 1

	return subtitles, num


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/segment/run', methods=['POST'])
def run_segment(proceso1_job_id: int):
	"""Extrae subtítulos nivel-oración del SRT, agrupados por sección.
	Usa word-level timestamps de _segments.json para reconstruir oraciones limpias.
	Luego Gemini decidirá cómo agrupar estos subtítulos en escenas (paso Enrich)."""
	get_or_create_job(proceso1_job_id)

	# Load markers + srt from Proceso 2
	concat_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='concat').first()
	srt_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='srt').first()

	if not concat_state:
		return jsonify({'error': 'Primero completa Proceso 2: Concat (markers.json)'}), 400
	if not srt_state:
		return jsonify({'error': 'Primero completa Proceso 2: SRT (final.srt)'}), 400

	markers_path_value = (concat_state.output_payload or {}).get('markersPath')
	srt_path_value = (srt_state.output_payload or {}).get('srtPath')

	markers: dict | None = None
	if markers_path_value:
		markers_path = Path(str(markers_path_value))
		if not markers_path.exists():
			return jsonify({'error': f'No se encontró markers.json en: {markers_path}'}), 400
		markers = json.loads(markers_path.read_text(encoding='utf-8'))
	else:
		markers = (concat_state.output_payload or {}).get('markers')

	if not isinstance(markers, dict) or not markers:
		return jsonify({'error': 'markers no válido en Proceso 2'}), 400

	if not srt_path_value:
		return jsonify({'error': 'No se encontró srtPath en Proceso 2'}), 400
	srt_path = Path(str(srt_path_value))
	if not srt_path.exists():
		return jsonify({'error': f'No se encontró SRT en: {srt_path}'}), 400

	# Prefer word-level timestamps from _segments.json
	segments_json_path = Path(str(srt_path).replace('.srt', '_segments.json'))
	all_words: list[dict] | None = None
	if segments_json_path.exists():
		raw_segments = json.loads(segments_json_path.read_text(encoding='utf-8'))
		all_words = _flatten_segment_words(raw_segments)

	# Fallback: parse SRT (no word-level data, each segment becomes a pseudo-subtitle)
	if not all_words:
		from ..proceso2.core.srt_generator import parse_srt_file
		srt_segments = parse_srt_file(str(srt_path))
		if not srt_segments:
			return jsonify({'error': 'No se encontraron segmentos en el SRT ni en _segments.json'}), 400
		all_words = [
			{'word': s['text'], 'start': s['start'], 'end': s['end']}
			for s in srt_segments if s.get('text', '').strip()
		]

	section_labels = [k for k in markers.keys() if not str(k).startswith('_')]
	section_labels.sort(key=lambda k: float((markers.get(k) or {}).get('start', 0.0)))

	subtitles_all: list[dict] = []
	subtitles_by_section: dict[str, list[dict]] = {}

	next_num = 1
	for raw_label in section_labels:
		info = markers.get(raw_label) or {}
		sec_start = float(info.get('start', 0.0))
		sec_end = float(info.get('end', 0.0))
		if sec_end <= sec_start:
			continue

		section = _normalize_section(str(raw_label))
		subs, next_num = _extract_sentence_subtitles(
			section_label=section,
			section_start=sec_start,
			section_end=sec_end,
			all_words=all_words,
			start_num=next_num,
		)

		subtitles_by_section[section] = subs
		subtitles_all.extend(subs)

	job_dir = get_job_dir(proceso1_job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	subtitles_path = output_dir / 'subtitles_by_section.json'
	subtitles_path.write_text(json.dumps(subtitles_by_section, ensure_ascii=False, indent=2), encoding='utf-8')

	stats = {
		'totalSubtitles': len(subtitles_all),
		'sections': {k: len(v) for k, v in subtitles_by_section.items()},
	}

	state = get_or_create_subprocess_state(proceso1_job_id, 'segment')
	payload = {
		'status': 'completed',
		'input': {
			'markersPath': str(markers_path) if markers_path_value else None,
			'srtPath': str(srt_path),
			'segmentsJsonPath': str(segments_json_path) if segments_json_path.exists() else None,
		},
		'output': {
			'subtitlesPath': str(subtitles_path),
			'subtitles': subtitles_all,
			'subtitlesBySection': subtitles_by_section,
			'stats': stats,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


def _gemini_enrich_prompt(subtitles: list[dict], section: str, context: dict | None = None) -> str:
	"""Prompt que le pide a Gemini AGRUPAR subtítulos en escenas Y asignar visuales.
	Si se pasa `context` (de _get_proceso1_context), se inyecta un bloque VIDEO CONTEXT
	con tema_principal, keywords, título/contexto de la sección y secciones vecinas."""
	visual_types = ["Animation", "Graphic", "B-roll", "Stock", "Text", "Screen Recording"]

	ctx = context or {}
	tema_principal   = str(ctx.get('tema_principal') or '').strip()
	keywords         = ctx.get('keywords') or []
	section_titulo   = str(ctx.get('section_titulo') or '').strip()
	section_contexto = str(ctx.get('section_contexto') or '').strip()
	prev_section     = str(ctx.get('prev_section_titulo') or '').strip()
	next_section     = str(ctx.get('next_section_titulo') or '').strip()

	context_lines: list[str] = []
	if tema_principal:
		context_lines.append(f'- Video topic: {tema_principal}')
	if keywords:
		context_lines.append(f'- Key scientific terms: {", ".join(keywords)}')
	if section_titulo:
		context_lines.append(f'- This section title: {section_titulo}')
	if section_contexto:
		context_lines.append(f'- This section covers: {section_contexto}')
	if prev_section:
		context_lines.append(f'- Previous section: {prev_section}')
	if next_section:
		context_lines.append(f'- Next section: {next_section}')

	context_block = ''
	if context_lines:
		context_block = 'VIDEO CONTEXT:\n' + '\n'.join(context_lines) + '\n\n'

	system = (
		"ROLE: Science Communicator Scriptwriter for YouTube.\n"
		"You will receive SRT subtitles from a section of the video"
		+ (" and rich context about the video" if context_block else "")
		+ ". Each subtitle has: num, start, end, text.\n\n"
		+ context_block
		+ "YOUR TASK:\n"
		"1. GROUP the subtitles into scenes. Each scene is a coherent visual unit (3-10 seconds).\n"
		"   - Combine subtitles that deal with the SAME visual concept.\n"
		"   - Separate when the image the viewer should see changes.\n"
		"   - A scene can contain 1, 2, or 3 subtitles.\n"
		"   - The scene text is the concatenation of the subtitles it groups.\n"
		"   - start = start of the first subtitle in the group; end = end of the last.\n\n"
		"2. For each scene, decide:\n"
		f"   - visual_type: exactly one of [{', '.join(visual_types)}]\n"
		"   - visual_description: brief 1-line description of the ideal visual. Your target audience is American, so use US customary units (miles, feet, Fahrenheit, etc.) naturally when mentioning measurements. Do not explicitly state that you are doing this for Americans.\n"
		"3. For each scene, extract physical_composition:\n"
		"   Read the grouped subtitle text carefully. Identify and list the REAL, LITERAL astronomical or physical objects and materials mentioned or implied (e.g. 'spiral galaxies, primordial hydrogen gas, dark matter filaments, ionized plasma, rocky asteroids, neutron star surface').\n"
		"   STRICT RULES for physical_composition:\n"
		"   - NO metaphors, NO sci-fi energy beams, NO magic, NO lightning, NO abstract art.\n"
		"   - Only real astrophysical or natural objects that a BBC/National Geographic VFX team would use as reference.\n"
		"   - If the text uses a poetic metaphor (e.g. 'gears of the universe', 'cosmic current', 'threads'), translate it to its physical equivalent (e.g. 'rotating galaxy filament composed of galaxy clusters and gas', 'gravitational flow of baryonic matter').\n"
		"   - Write it as a short comma-separated list in English.\n\n"
		"Reply ONLY with a JSON array. Each element:\n"
		"{\n"
		'  "scene_num": N,\n'
		f'  "section": "{section}",\n'
		'  "start": first_start_of_the_group,\n'
		'  "end": last_end_of_the_group,\n'
		'  "text": "concatenated text of the group",\n'
		'  "duration": end - start,\n'
		'  "visual_type": "...",\n'
		'  "visual_description": "...",\n'
		'  "physical_composition": "real physical objects list in English"\n'
		"}\n\n"
		"IMPORTANT: scene_num must be sequential starting from 1.\n"
		"Do not add explanations outside the JSON."
	)
	subs_json = json.dumps(
		[
			{
				'num': s.get('num'),
				'start': s.get('start'),
				'end': s.get('end'),
				'text': s.get('text'),
			}
			for s in subtitles
		],
		ensure_ascii=False,
		indent=2,
	)
	return f"{system}\n\nSubtitles of the section [{section}]:\n{subs_json}"


def _mask_api_key(api_key: str) -> str:
	if not api_key:
		return '<missing>'
	if len(api_key) <= 10:
		return api_key[:2] + '***'
	return f"{api_key[:8]}...{api_key[-4:]}"


def _compact_text(value: str, limit: int = 400) -> str:
	text = re.sub(r"\s+", " ", str(value or '')).strip()
	if len(text) <= limit:
		return text
	return text[:limit] + '...'


def _extract_retry_delay_seconds(error_text: str) -> int | None:
	match = re.search(r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s", error_text or '', re.IGNORECASE)
	if match:
		return int(float(match.group(1)))
	match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)\s*\}", error_text or '', re.IGNORECASE)
	if match:
		return int(match.group(1))
	return None


def _extract_quota_detail(error_text: str, field: str) -> str | None:
	match = re.search(rf'{re.escape(field)}:\s*"([^"]+)"', error_text or '', re.IGNORECASE)
	if match:
		return match.group(1)
	return None


def _next_gemini_call_id() -> int:
	global _GEMINI_CALL_SEQUENCE
	_GEMINI_CALL_SEQUENCE += 1
	return _GEMINI_CALL_SEQUENCE


def _write_enrich_debug_file(proceso1_job_id: int, section: str, suffix: str, payload: dict) -> str:
	debug_dir = get_job_dir(proceso1_job_id) / 'debug'
	debug_dir.mkdir(parents=True, exist_ok=True)
	timestamp = time.strftime('%Y%m%d_%H%M%S')
	path = debug_dir / f'enrich_{section}_{timestamp}_{suffix}.json'
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
	return str(path)


def _call_gemini(prompt: str, *, proceso1_job_id: int | None = None, section: str | None = None) -> str:
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
	api_source = 'flask_config'
	if not api_key:
		# Fallback just in case config doesn't have it initialized via current_app yet?
		from config import GEMINI_API_KEY, GEMINI_MODEL
		api_key = GEMINI_API_KEY
		model_name = GEMINI_MODEL
		api_source = 'config_fallback'
		
	if not api_key:
		raise RuntimeError('GEMINI_API_KEY no está configurada en el backend')

	try:
		import google.generativeai as genai
	except ImportError as exc:
		raise RuntimeError('Falta dependencia: pip install google-generativeai') from exc

	call_id = _next_gemini_call_id()
	started = time.perf_counter()
	prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]
	try:
		current_app.logger.info(
			"[P3 gemini] start call=%s job=%s section=%s model=%s apiSource=%s apiKey=%s promptChars=%s promptHash=%s promptPreview=%r",
			call_id,
			proceso1_job_id,
			section,
			model_name,
			api_source,
			_mask_api_key(api_key),
			len(prompt),
			prompt_hash,
			_compact_text(prompt, 500),
		)
	except Exception:
		pass

	genai.configure(api_key=api_key)
	model = genai.GenerativeModel(model_name)
	try:
		resp = model.generate_content(prompt)
		latency_ms = int((time.perf_counter() - started) * 1000)
		response_text = resp.text or ''
		usage_meta = getattr(resp, 'usage_metadata', None)
		feedback = getattr(resp, 'prompt_feedback', None)
		try:
			current_app.logger.info(
				"[P3 gemini] success call=%s job=%s section=%s latencyMs=%s rawChars=%s usage=%r feedback=%r",
				call_id,
				proceso1_job_id,
				section,
				latency_ms,
				len(response_text),
				usage_meta,
				feedback,
			)
		except Exception:
			pass
		return response_text
	except Exception as exc:
		latency_ms = int((time.perf_counter() - started) * 1000)
		error_text = str(exc)
		retry_delay = _extract_retry_delay_seconds(error_text)
		quota_metric = _extract_quota_detail(error_text, 'quota_metric')
		quota_id = _extract_quota_detail(error_text, 'quota_id')
		quota_model = _extract_quota_detail(error_text, 'model')
		current_app.logger.exception(
			"[P3 gemini] error call=%s job=%s section=%s latencyMs=%s model=%s apiSource=%s apiKey=%s promptChars=%s promptHash=%s retryDelay=%s quotaMetric=%s quotaId=%s quotaModel=%s error=%s",
			call_id,
			proceso1_job_id,
			section,
			latency_ms,
			model_name,
			api_source,
			_mask_api_key(api_key),
			len(prompt),
			prompt_hash,
			retry_delay,
			quota_metric,
			quota_id,
			quota_model,
			error_text,
		)
		raise


def _sanitize_json_control_chars(json_str: str) -> str:
	"""Escape literal control characters inside JSON string values.
	Gemini sometimes emits raw newlines/tabs inside string values, which makes
	json.loads raise 'Invalid control character'. This walks the string char by char,
	tracking whether we're inside a JSON string, and replaces bare control chars
	with their proper JSON escape sequences."""
	_control_map = {'\n': '\\n', '\r': '\\r', '\t': '\\t', '\b': '\\b', '\f': '\\f'}
	result: list[str] = []
	in_string = False
	escaped = False
	for ch in json_str:
		if escaped:
			result.append(ch)
			escaped = False
		elif ch == '\\' and in_string:
			result.append(ch)
			escaped = True
		elif ch == '"':
			result.append(ch)
			in_string = not in_string
		elif in_string and ch in _control_map:
			result.append(_control_map[ch])
		else:
			result.append(ch)
	return ''.join(result)


def _parse_json_array(raw_text: str) -> list[dict]:
	import re

	match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text)
	if not match:
		match = re.search(r"```\s*([\s\S]*?)\s*```", raw_text)
	json_str = match.group(1) if match else raw_text
	json_str = _sanitize_json_control_chars(json_str)
	try:
		data = json.loads(json_str)
	except Exception:
		data = json.loads(json_str.strip())
	return data if isinstance(data, list) else []


def _compute_scene_num_offset(
	subtitles_by_section: dict[str, list[dict]],
	target_section: str,
	all_batch_states: list,
) -> int:
	"""Compute the starting scene_num for a section based on already-completed batches.
	This ensures globally-unique scene_nums across all sections."""
	offset = 1
	for st in all_batch_states:
		sec = (st.input_payload or {}).get('section', '')
		if sec == target_section:
			continue
		batch_scenes = (st.output_payload or {}).get('scenes') or []
		if batch_scenes and st.status == 'completed':
			# Only count scenes from completed sections that come BEFORE target
			# We use subtitle start times to determine section order
			my_subs = subtitles_by_section.get(sec, [])
			target_subs = subtitles_by_section.get(target_section, [])
			my_start = my_subs[0]['start'] if my_subs else float('inf')
			target_start = target_subs[0]['start'] if target_subs else float('inf')
			if my_start < target_start:
				offset += len(batch_scenes)
	return offset


def _get_segment_enrich_context(proceso1_job_id: int, section: str) -> tuple[dict[str, list[dict]], list[dict]]:
	segment_state = Proceso3SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='segment').first()
	if not segment_state or not (segment_state.output_payload or {}).get('subtitlesBySection'):
		raise ValueError('Primero ejecuta Proceso 3: Segment (subtítulos por sección)')

	subtitles_by_section = (segment_state.output_payload or {}).get('subtitlesBySection') or {}
	subtitles: list[dict] = subtitles_by_section.get(section) or []
	if not subtitles:
		raise ValueError(f'No hay subtítulos para la sección: {section}')
	return subtitles_by_section, subtitles


def _get_proceso1_context(proceso1_job_id: int, section: str, subtitles_by_section: dict) -> dict:
	"""Load video-level context from Proceso 1's estructura (subproceso2) to enrich the prompt.
	Returns an empty dict if the data is not available — the prompt degrades gracefully."""
	try:
		p1_state = Proceso1SubprocessState.query.filter_by(
			job_id=proceso1_job_id,
			subprocess_key='subproceso2',
		).first()
		if not p1_state or not p1_state.output_payload:
			return {}

		estructura = (p1_state.output_payload or {}).get('estructura') or {}
		if not estructura:
			return {}

		tema_principal = str(estructura.get('tema_principal') or '').strip()
		raw_kw = estructura.get('keywords') or []
		keywords = [str(k).strip() for k in raw_kw if str(k).strip()]
		subtemas = estructura.get('subtemas') or []

		# Sort sections by first subtitle start to establish order (intro → partes → cierre)
		section_order = sorted(
			[s for s in subtitles_by_section if subtitles_by_section.get(s)],
			key=lambda s: subtitles_by_section[s][0].get('start', float('inf')),
		)

		try:
			idx = section_order.index(section)
		except ValueError:
			idx = -1

		# Mapping: position 0 = intro (no subtema), 1..M = subtemas[0..M-1], last ≈ cierre
		section_titulo = ''
		section_contexto = ''
		prev_section_titulo = ''
		next_section_titulo = ''

		if idx >= 0:
			subtema_idx = idx - 1  # intro at idx=0 → subtema_idx=-1
			if 0 <= subtema_idx < len(subtemas):
				section_titulo = str(subtemas[subtema_idx].get('titulo') or '').strip()
				section_contexto = str(subtemas[subtema_idx].get('contexto') or '').strip()

			# Previous section label
			if idx > 0:
				prev_subtema_idx = idx - 2
				if 0 <= prev_subtema_idx < len(subtemas):
					prev_section_titulo = str(subtemas[prev_subtema_idx].get('titulo') or '').strip()
				elif idx - 1 == 0:
					prev_section_titulo = 'Introduction'

			# Next section label
			if idx < len(section_order) - 1:
				next_subtema_idx = idx  # next position is idx+1, its subtema_idx = idx
				if 0 <= next_subtema_idx < len(subtemas):
					next_section_titulo = str(subtemas[next_subtema_idx].get('titulo') or '').strip()
				elif idx + 1 == len(section_order) - 1:
					next_section_titulo = 'Conclusion / Closing'

		return {
			'tema_principal': tema_principal,
			'keywords': keywords,
			'section_titulo': section_titulo,
			'section_contexto': section_contexto,
			'prev_section_titulo': prev_section_titulo,
			'next_section_titulo': next_section_titulo,
		}
	except Exception:
		return {}


def _validate_and_normalize_scenes(raw_scenes: list[dict], section: str) -> list[dict]:
	if not isinstance(raw_scenes, list):
		raise ValueError('El JSON manual debe ser un array de escenas')
	if not raw_scenes:
		raise ValueError('El JSON manual no contiene escenas')

	normalized: list[dict] = []
	for index, scene in enumerate(raw_scenes, start=1):
		if not isinstance(scene, dict):
			raise ValueError(f'La escena {index} no es un objeto JSON válido')

		missing_fields = [key for key in ('start', 'end', 'text') if key not in scene]
		if missing_fields:
			raise ValueError(f'La escena {index} no tiene los campos requeridos: {", ".join(missing_fields)}')

		try:
			start = round(float(scene.get('start')), 3)
			end = round(float(scene.get('end')), 3)
		except (TypeError, ValueError) as exc:
			raise ValueError(f'La escena {index} debe tener start/end numéricos') from exc

		if end < start:
			raise ValueError(f'La escena {index} tiene end menor que start')

		text = str(scene.get('text') or '').strip()
		if not text:
			raise ValueError(f'La escena {index} tiene text vacío')

		normalized_scene = dict(scene)
		normalized_scene['start'] = start
		normalized_scene['end'] = end
		normalized_scene['text'] = text
		normalized_scene['section'] = section
		normalized_scene['visual_type'] = str(scene.get('visual_type') or 'B-roll').strip() or 'B-roll'
		normalized_scene['visual_description'] = str(scene.get('visual_description') or '').strip()
		normalized_scene['physical_composition'] = str(scene.get('physical_composition') or '').strip()
		duration = scene.get('duration')
		if duration in (None, ''):
			normalized_scene['duration'] = round(end - start, 2)
		else:
			try:
				normalized_scene['duration'] = round(float(duration), 2)
			except (TypeError, ValueError) as exc:
				raise ValueError(f'La escena {index} tiene duration inválido') from exc
		normalized.append(normalized_scene)

	return normalized


def _log_enrich_scene_preview(proceso1_job_id: int, section: str, scenes: list[dict], subtitles: list[dict]) -> None:
	try:
		missing_visuals = sum(1 for s in scenes if not str(s.get('visual_description') or '').strip())
		ratio = round((len(scenes) / max(1, len(subtitles))), 3)
		current_app.logger.info(
			"[P3 enrich] parsed scenes job=%s section=%s scenes=%s subtitles=%s ratio=%s missingVisualDesc=%s",
			proceso1_job_id,
			section,
			len(scenes),
			len(subtitles),
			ratio,
			missing_visuals,
		)
		for preview in scenes[:3]:
			text_preview = re.sub(r"\s+", " ", str(preview.get('text') or '')).strip()
			if len(text_preview) > 140:
				text_preview = text_preview[:140] + '…'
			vis = str(preview.get('visual_type') or '')
			vdesc = re.sub(r"\s+", " ", str(preview.get('visual_description') or '')).strip()
			if len(vdesc) > 160:
				vdesc = vdesc[:160] + '…'
			current_app.logger.info(
				"[P3 enrich] scene_preview #%s %ss-%ss type=%s text=%r visual=%r",
				preview.get('scene_num'),
				preview.get('start'),
				preview.get('end'),
				vis,
				text_preview,
				vdesc,
			)
	except Exception:
		pass


def _save_enrich_batch(
	proceso1_job_id: int,
	section: str,
	raw_scenes: list[dict],
	*,
	raw_response: str | None = None,
	prompt_used: str | None = None,
	latency_ms: int | None = None,
) -> Proceso3SubprocessState:
	subtitles_by_section, subtitles = _get_segment_enrich_context(proceso1_job_id, section)
	scenes = _validate_and_normalize_scenes(raw_scenes, section)

	batch_states = Proceso3SubprocessState.query.filter(
		Proceso3SubprocessState.proceso1_job_id == proceso1_job_id,
		Proceso3SubprocessState.subprocess_key.like('batch_%'),
	).all()
	offset = _compute_scene_num_offset(subtitles_by_section, section, batch_states)

	for i, scene in enumerate(scenes):
		scene['scene_num'] = offset + i
		scene['section'] = section
		if 'duration' not in scene or scene['duration'] in (None, ''):
			scene['duration'] = round(float(scene['end']) - float(scene['start']), 2)
		if 'visual_type' not in scene:
			scene['visual_type'] = 'B-roll'
		if 'visual_description' not in scene:
			scene['visual_description'] = ''
		if 'physical_composition' not in scene:
			scene['physical_composition'] = ''

	_log_enrich_scene_preview(proceso1_job_id, section, scenes, subtitles)

	job_dir = get_job_dir(proceso1_job_id)
	batches_dir = job_dir / 'output' / 'batches'
	batches_dir.mkdir(parents=True, exist_ok=True)
	batch_path = batches_dir / f'batch_{section}.json'
	batch_path.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding='utf-8')

	state = get_or_create_subprocess_state(proceso1_job_id, f'batch_{section}')
	metadata: dict[str, object] = {}
	if raw_response is not None:
		metadata['rawResponse'] = raw_response
	if prompt_used is not None:
		metadata['promptUsed'] = prompt_used
	payload = {
		'status': 'completed',
		'input': {
			'section': section,
			'subtitleCount': len(subtitles),
		},
		'output': {
			'batchPath': str(batch_path),
			'scenes': scenes,
			'sceneCount': len(scenes),
			'latencyMs': latency_ms,
		},
		'metadata': metadata,
	}
	return _save_state(state, payload)


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/enrich-section/prompt', methods=['GET'])
def get_enrich_prompt(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	section = _normalize_section(str(request.args.get('section') or ''))
	if not section:
		return jsonify({'error': 'Falta query param: section'}), 400

	try:
		subtitles_by_section, subtitles = _get_segment_enrich_context(proceso1_job_id, section)
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400

	video_context = _get_proceso1_context(proceso1_job_id, section, subtitles_by_section)
	prompt = _gemini_enrich_prompt(subtitles, section, context=video_context)
	return jsonify({
		'section': section,
		'subtitleCount': len(subtitles),
		'prompt': prompt,
	})


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/enrich-section/manual', methods=['POST'])
def save_manual_enrich_section(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	section = _normalize_section(str(body.get('section') or ''))
	if not section:
		return jsonify({'error': 'Falta field: section'}), 400

	raw_response = body.get('rawResponse')
	prompt_used = body.get('promptUsed')
	scenes = body.get('scenes')
	json_text = body.get('jsonText')
	if scenes is None:
		if not str(json_text or '').strip():
			return jsonify({'error': 'Debes enviar scenes o jsonText'}), 400
		try:
			scenes = _parse_json_array(str(json_text))
		except Exception as exc:
			return jsonify({'error': f'No se pudo parsear el JSON manual: {str(exc)}'}), 400

	try:
		saved = _save_enrich_batch(
			proceso1_job_id,
			section,
			scenes,
			raw_response=str(raw_response) if raw_response is not None else (str(json_text) if json_text is not None else None),
			prompt_used=str(prompt_used) if prompt_used is not None else None,
			latency_ms=None,
		)
		return jsonify(saved.to_dict())
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/enrich-section/run', methods=['POST'])
def run_enrich_section(proceso1_job_id: int):
	"""Envía subtítulos de UNA sección a Gemini. Gemini los agrupa en escenas Y asigna visuales.
	Replica el comportamiento legacy: 18 subtítulos → 14 escenas (Gemini decide agrupación).
	Cada sección = 1 prompt. El frontend se encarga del cooldown de 65s entre secciones."""
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	section = _normalize_section(str(body.get('section') or ''))
	if not section:
		return jsonify({'error': 'Falta field: section'}), 400

	try:
		subtitles_by_section, subtitles = _get_segment_enrich_context(proceso1_job_id, section)
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400

	# Marcar como "running" en BD antes de llamar a Gemini
	state = get_or_create_subprocess_state(proceso1_job_id, f'batch_{section}')
	_save_state(state, {'status': 'running', 'input': {'section': section, 'subtitleCount': len(subtitles)}})

	try:
		current_app.logger.info(
			"[P3 enrich] job=%s section=%s subtitles=%s first=(%ss→%ss) last=(%ss→%ss)",
			proceso1_job_id,
			section,
			len(subtitles),
			subtitles[0].get('start'),
			subtitles[0].get('end'),
			subtitles[-1].get('start'),
			subtitles[-1].get('end'),
		)
	except Exception:
		# Avoid breaking endpoint if logger isn't configured
		pass

	started = time.perf_counter()

	try:
		# 1 sola llamada a Gemini con TODOS los subtítulos de la sección.
		# Gemini agrupa en escenas + asigna visual_type/visual_description.
		video_context = _get_proceso1_context(proceso1_job_id, section, subtitles_by_section)
		prompt = _gemini_enrich_prompt(subtitles, section, context=video_context)
		prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]
		request_debug_path = _write_enrich_debug_file(
			proceso1_job_id,
			section,
			'request',
			{
				'jobId': proceso1_job_id,
				'section': section,
				'subtitleCount': len(subtitles),
				'promptChars': len(prompt),
				'promptHash': prompt_hash,
				'model': current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview'),
				'apiKeyMasked': _mask_api_key(current_app.config.get('GEMINI_API_KEY', '')),
				'prompt': prompt,
				'subtitles': subtitles,
			},
		)
		try:
			current_app.logger.info(
				"[P3 enrich] calling Gemini job=%s section=%s promptChars=%s promptHash=%s debugRequest=%s",
				proceso1_job_id,
				section,
				len(prompt),
				prompt_hash,
				request_debug_path,
			)
		except Exception:
			pass
		raw = _call_gemini(prompt, proceso1_job_id=proceso1_job_id, section=section)
		response_debug_path = _write_enrich_debug_file(
			proceso1_job_id,
			section,
			'response',
			{
				'jobId': proceso1_job_id,
				'section': section,
				'promptHash': prompt_hash,
				'rawResponse': raw,
			},
		)
		try:
			current_app.logger.info(
				"[P3 enrich] Gemini response job=%s section=%s rawChars=%s debugResponse=%s",
				proceso1_job_id,
				section,
				len(raw or ''),
				response_debug_path,
			)
		except Exception:
			pass
		scenes = _parse_json_array(raw)
		if not scenes:
			try:
				current_app.logger.warning(
					"[P3 enrich] EMPTY scenes parsed job=%s section=%s (raw head)=%r",
					proceso1_job_id,
					section,
					(raw or '')[:300],
				)
			except Exception:
				pass

		latency_ms = int((time.perf_counter() - started) * 1000)
		saved = _save_enrich_batch(
			proceso1_job_id,
			section,
			scenes,
			raw_response=raw,
			prompt_used=prompt,
			latency_ms=latency_ms,
		)
		return jsonify(saved.to_dict())
	except Exception as e:
		# Revert to error state
		error_payload = {
			'status': 'error',
			'metadata': {
				'error': str(e),
			},
		}
		try:
			error_debug_path = _write_enrich_debug_file(
				proceso1_job_id,
				section,
				'error',
				{
					'jobId': proceso1_job_id,
					'section': section,
					'error': str(e),
					'retryDelaySeconds': _extract_retry_delay_seconds(str(e)),
					'quotaMetric': _extract_quota_detail(str(e), 'quota_metric'),
					'quotaId': _extract_quota_detail(str(e), 'quota_id'),
					'quotaModel': _extract_quota_detail(str(e), 'model'),
				},
			)
			current_app.logger.error(
				"[P3 enrich] failed job=%s section=%s debugError=%s",
				proceso1_job_id,
				section,
				error_debug_path,
			)
		except Exception:
			pass
		_save_state(state, error_payload)
		return jsonify({'error': f'Error enriqueciendo sección {section}: {str(e)}'}), 500


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/timeline/run', methods=['POST'])
def run_timeline(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)

	# Collect all batch_* states for this job
	batch_states = Proceso3SubprocessState.query.filter(
		Proceso3SubprocessState.proceso1_job_id == proceso1_job_id,
		Proceso3SubprocessState.subprocess_key.like('batch_%'),
	).all()

	scenes: list[dict] = []
	for st in batch_states:
		batch_scenes = (st.output_payload or {}).get('scenes')
		if isinstance(batch_scenes, list):
			scenes.extend(batch_scenes)

	if not scenes:
		return jsonify({'error': 'No hay batches enriquecidos. Ejecuta Enrich por sección (batch_intro, batch_parte1, etc.).'}), 400

	scenes.sort(key=lambda s: float(s.get('start', 0.0)))

	# Re-number scene_nums globally (1..N) so they are always sequential
	# regardless of the order sections were enriched.
	for i, scene in enumerate(scenes):
		scene['scene_num'] = i + 1

	timeline = {
		'proceso1JobId': proceso1_job_id,
		'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
		'batches': sorted([st.subprocess_key for st in batch_states]),
		'scenes': scenes,
	}

	job_dir = get_job_dir(proceso1_job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	timeline_path = output_dir / 'timeline.json'
	timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')

	state = get_or_create_subprocess_state(proceso1_job_id, 'timeline')
	payload = {
		'status': 'completed',
		'input': {
			'source': 'batch_*',
		},
		'output': {
			'timelinePath': str(timeline_path),
			'timeline': timeline,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


def _get_final_mp3_path_from_proceso2(proceso1_job_id: int) -> Path | None:
	"""Return the Proceso2 concat final.mp3 path for this job if available."""
	concat_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='concat').first()
	final_mp3 = (concat_state.output_payload or {}).get('finalMp3') if concat_state else None
	if not final_mp3:
		return None
	path = Path(str(final_mp3))
	return path if path.exists() else None


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/audio', methods=['GET'])
def get_job_audio(proceso1_job_id: int):
	"""Serve the concatenated narration audio (Proceso2 concat -> final.mp3)."""
	get_or_create_job(proceso1_job_id)
	path = _get_final_mp3_path_from_proceso2(proceso1_job_id)
	if not path:
		return jsonify({'error': 'No se encontró final.mp3. Ejecuta Proceso 2: Concat primero.'}), 400
	# Allow streaming/range requests for <audio> element
	return send_file(str(path), mimetype='audio/mpeg', as_attachment=False, conditional=True)


def _collect_enriched_scenes_for_job(proceso1_job_id: int) -> list[dict]:
	"""Collect all enriched scenes across batch_* states, sorted by start time."""
	batch_states = Proceso3SubprocessState.query.filter(
		Proceso3SubprocessState.proceso1_job_id == proceso1_job_id,
		Proceso3SubprocessState.subprocess_key.like('batch_%'),
	).all()
	items: list[dict] = []
	for st in batch_states:
		batch_scenes = (st.output_payload or {}).get('scenes')
		if isinstance(batch_scenes, list):
			items.extend(batch_scenes)
	items.sort(key=lambda s: float(s.get('start', 0.0)))
	return items


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/exports/markers.csv', methods=['GET'])
def export_markers_csv(proceso1_job_id: int):
	"""Export enriched scenes as a CSV marker list (for editing workflows).

	Columns include subtema/section, start/end, and the Gemini visual guidance.
	"""
	get_or_create_job(proceso1_job_id)

	# Prefer timeline state (it already aggregates), fallback to batch_*.
	timeline_state = Proceso3SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key='timeline',
	).first()
	scenes: list[dict] = []
	if timeline_state and isinstance((timeline_state.output_payload or {}).get('timeline'), dict):
		timeline = (timeline_state.output_payload or {}).get('timeline') or {}
		scenes = timeline.get('scenes') or []
	if not isinstance(scenes, list) or not scenes:
		scenes = _collect_enriched_scenes_for_job(proceso1_job_id)

	if not scenes:
		return jsonify({'error': 'No hay escenas enriquecidas para exportar. Ejecuta Enrich por sección primero.'}), 400

	import csv
	import io

	buf = io.StringIO()
	writer = csv.writer(buf)
	writer.writerow([
		'scene_num',
		'subtema',
		'start_s',
		'end_s',
		'duration_s',
		'marker_name',
		'visual_type',
		'visual_description',
		'text',
	])

	for s in scenes:
		scene_num = s.get('scene_num', '')
		section = s.get('section', '')
		start = float(s.get('start', 0.0) or 0.0)
		end = float(s.get('end', 0.0) or 0.0)
		duration = float(s.get('duration', (end - start)) or (end - start))
		visual_type = s.get('visual_type', '')
		visual_desc = s.get('visual_description', '')
		text = s.get('text', '')
		marker_name = f"S{scene_num} [{section}] {visual_type}".strip()
		writer.writerow([
			scene_num,
			section,
			round(start, 3),
			round(end, 3),
			round(duration, 3),
			marker_name,
			visual_type,
			visual_desc,
			text,
		])

	content = buf.getvalue().encode('utf-8-sig')
	resp = make_response(content)
	resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
	resp.headers['Content-Disposition'] = f'attachment; filename="proceso3_job_{proceso1_job_id}_markers.csv"'
	return resp


def _get_scenes_for_export(proceso1_job_id: int) -> list[dict]:
	"""Get scenes for export (prefer timeline state, fallback to batch_*)."""
	timeline_state = Proceso3SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key='timeline',
	).first()
	if timeline_state and isinstance((timeline_state.output_payload or {}).get('timeline'), dict):
		timeline = (timeline_state.output_payload or {}).get('timeline') or {}
		scenes = timeline.get('scenes') or []
		if isinstance(scenes, list) and scenes:
			return scenes
	return _collect_enriched_scenes_for_job(proceso1_job_id)


def _fmt_seconds(seconds: float) -> str:
	return f"{float(seconds):.3f}s"


def _seconds_to_tc(seconds: float, fps: int) -> str:
	"""Convert seconds to non-drop timecode HH:MM:SS:FF."""
	fps = int(fps) if int(fps) > 0 else 30
	total_frames = int(round(float(seconds) * fps))
	frames = total_frames % fps
	total_seconds = total_frames // fps
	ss = total_seconds % 60
	mm = (total_seconds // 60) % 60
	hh = total_seconds // 3600
	return f"{hh:02d}:{mm:02d}:{ss:02d}:{frames:02d}"


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/exports/premiere.fcpxml', methods=['GET'])
def export_fcpxml(proceso1_job_id: int):
	"""Export a FCPXML timeline for Premiere import.

	- Contains the full narration audio as a single clip.
	- Adds 1 marker per scene with duration = scene duration (so it shows a RANGE).
	- Marker name includes subtema/section + visual guidance.
	"""
	get_or_create_job(proceso1_job_id)
	path = _get_final_mp3_path_from_proceso2(proceso1_job_id)
	if not path:
		return jsonify({'error': 'No se encontró final.mp3. Ejecuta Proceso 2: Concat primero.'}), 400

	scenes = _get_scenes_for_export(proceso1_job_id)
	if not scenes:
		return jsonify({'error': 'No hay escenas enriquecidas para exportar. Ejecuta Enrich por sección primero.'}), 400

	# Optional fps override
	try:
		fps = int(request.args.get('fps') or 30)
	except Exception:
		fps = 30
	if fps <= 0:
		fps = 30

	from xml.sax.saxutils import escape as xml_escape

	total_end = max(float(s.get('end', 0.0) or 0.0) for s in scenes)
	asset_uri = path.resolve().as_uri()

	# Minimal FCPXML 1.10 structure
	markers_xml = []
	for s in scenes:
		start = float(s.get('start', 0.0) or 0.0)
		end = float(s.get('end', 0.0) or 0.0)
		dur = float(s.get('duration', (end - start)) or (end - start))
		sec = str(s.get('section', '') or '')
		sn = str(s.get('scene_num', '') or '')
		vt = str(s.get('visual_type', '') or '')
		vd = str(s.get('visual_description', '') or '')
		label = f"S{sn} [{sec}] {vt} | {vd}".strip()
		markers_xml.append(
			f"<marker start=\"{_fmt_seconds(start)}\" duration=\"{_fmt_seconds(max(0.001, dur))}\" value=\"{xml_escape(label)}\"/>"
		)

	xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<fcpxml version=\"1.10\">
  <resources>
    <format id=\"r1\" name=\"FFVideoFormat1080p{fps}\" frameDuration=\"1/{fps}s\" width=\"1920\" height=\"1080\"/>
    <asset id=\"r2\" name=\"final.mp3\" src=\"{xml_escape(asset_uri)}\" start=\"0s\" duration=\"{_fmt_seconds(total_end)}\" hasAudio=\"1\" audioSources=\"1\" audioChannels=\"2\" format=\"r1\"/>
  </resources>
  <library>
    <event name=\"Scienceluxe\">
      <project name=\"Proceso3 Job {proceso1_job_id}\">
        <sequence duration=\"{_fmt_seconds(total_end)}\" format=\"r1\">
          <spine>
            <asset-clip ref=\"r2\" name=\"final.mp3\" offset=\"0s\" start=\"0s\" duration=\"{_fmt_seconds(total_end)}\">
              {''.join(markers_xml)}
            </asset-clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

	resp = make_response(xml.encode('utf-8'))
	resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
	resp.headers['Content-Disposition'] = f'attachment; filename="proceso3_job_{proceso1_job_id}_premiere.fcpxml"'
	return resp


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/exports/premiere.edl', methods=['GET'])
def export_edl(proceso1_job_id: int):
	"""Export a simple CMX3600 EDL with dummy V cuts aligned to scene ranges.

Note: EDL is limited; this is mainly to get the CUT POINTS into an NLE.
"""
	get_or_create_job(proceso1_job_id)

	scenes = _get_scenes_for_export(proceso1_job_id)
	if not scenes:
		return jsonify({'error': 'No hay escenas enriquecidas para exportar. Ejecuta Enrich por sección primero.'}), 400

	# Optional fps override
	try:
		fps = int(request.args.get('fps') or 30)
	except Exception:
		fps = 30
	if fps <= 0:
		fps = 30

	lines: list[str] = []
	lines.append(f"TITLE: Proceso3 Job {proceso1_job_id}")
	lines.append("FCM: NON-DROP FRAME")
	lines.append("")

	for idx, s in enumerate(scenes, start=1):
		start = float(s.get('start', 0.0) or 0.0)
		end = float(s.get('end', 0.0) or 0.0)
		sn = str(s.get('scene_num', idx) or idx)
		sec = str(s.get('section', '') or '')
		vt = str(s.get('visual_type', '') or '')
		vd = str(s.get('visual_description', '') or '')

		rec_in = _seconds_to_tc(start, fps)
		rec_out = _seconds_to_tc(end, fps)
		# Use the same as source; this is dummy/filler aligned to record timeline
		src_in = rec_in
		src_out = rec_out
		event = f"{idx:03d}  BL      V     C        {src_in} {src_out} {rec_in} {rec_out}"
		lines.append(event)
		lines.append(f"* FROM CLIP NAME: S{sn} [{sec}] {vt}".strip())
		if vd:
			lines.append(f"* COMMENT: {vd}")
		lines.append("")

	edl = "\n".join(lines)
	resp = make_response(edl.encode('utf-8-sig'))
	resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
	resp.headers['Content-Disposition'] = f'attachment; filename="proceso3_job_{proceso1_job_id}_premiere.edl"'
	return resp


@proceso3_bp.route('/jobs/<int:proceso1_job_id>/exports/premiere.xml', methods=['GET'])
def export_premiere_fcp7_xml(proceso1_job_id: int):
	"""Export Final Cut Pro 7 XML (xmeml) which Premiere Pro can usually import.

	This creates:
	- A sequence with the full narration audio placed at 0.
	- Sequence markers spanning each scene range (in/out).

	Why: Premiere often cannot import modern FCPXML (.fcpxml) directly.
	"""
	get_or_create_job(proceso1_job_id)
	path = _get_final_mp3_path_from_proceso2(proceso1_job_id)
	if not path:
		return jsonify({'error': 'No se encontró final.mp3. Ejecuta Proceso 2: Concat primero.'}), 400

	scenes = _get_scenes_for_export(proceso1_job_id)
	if not scenes:
		return jsonify({'error': 'No hay escenas enriquecidas para exportar. Ejecuta Enrich por sección primero.'}), 400

	try:
		fps = int(request.args.get('fps') or 30)
	except Exception:
		fps = 30
	if fps <= 0:
		fps = 30

	def to_frames(sec: float) -> int:
		return int(round(float(sec) * fps))

	total_end = max(float(s.get('end', 0.0) or 0.0) for s in scenes)
	seq_duration = to_frames(total_end)
	file_uri = path.resolve().as_uri()

	from xml.sax.saxutils import escape as xml_escape

	# FCP7 XML (xmeml) expects local file URLs; as_uri() gives file:///C:/...
	project_name = f"Proceso3 Job {proceso1_job_id}"
	sequence_name = f"Secuencia Job {proceso1_job_id}"

	markers_xml: list[str] = []
	for s in scenes:
		start = float(s.get('start', 0.0) or 0.0)
		end = float(s.get('end', 0.0) or 0.0)
		sn = str(s.get('scene_num', '') or '')
		sec = str(s.get('section', '') or '')
		vt = str(s.get('visual_type', '') or '')
		vd = str(s.get('visual_description', '') or '')
		label = f"S{sn} [{sec}] {vt}".strip()
		comment = vd.strip() if vd else ''
		markers_xml.append(
			"<marker>"
			f"<name>{xml_escape(label)}</name>"
			f"<comment>{xml_escape(comment)}</comment>"
			f"<in>{to_frames(start)}</in>"
			f"<out>{max(to_frames(end), to_frames(start) + 1)}</out>"
			"</marker>"
		)

	# One audio clip item spanning the full duration.
	clipitem_id = "clipitem-1"
	file_id = "file-1"

	xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<xmeml version=\"5\">
  <project>
    <name>{xml_escape(project_name)}</name>
    <children>
      <sequence id=\"sequence-1\">
        <name>{xml_escape(sequence_name)}</name>
        <duration>{seq_duration}</duration>
        <rate>
          <timebase>{fps}</timebase>
          <ntsc>FALSE</ntsc>
        </rate>
        {''.join(markers_xml)}
        <media>
          <audio>
            <track>
              <clipitem id=\"{clipitem_id}\">
                <name>{xml_escape(path.name)}</name>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{seq_duration}</end>
                <in>0</in>
                <out>{seq_duration}</out>
                <file id=\"{file_id}\">
                  <name>{xml_escape(path.name)}</name>
                  <pathurl>{xml_escape(file_uri)}</pathurl>
                  <rate>
                    <timebase>{fps}</timebase>
                    <ntsc>FALSE</ntsc>
                  </rate>
                  <media>
                    <audio>
                      <channelcount>2</channelcount>
                    </audio>
                  </media>
                </file>
              </clipitem>
            </track>
          </audio>
        </media>
      </sequence>
    </children>
  </project>
</xmeml>
"""

	resp = make_response(xml.encode('utf-8'))
	resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
	resp.headers['Content-Disposition'] = f'attachment; filename="proceso3_job_{proceso1_job_id}_premiere.xml"'
	return resp


__all__ = [
	'proceso3_bp',
]
