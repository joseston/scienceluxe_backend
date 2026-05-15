"""Proceso 3 Corto — Enriquecimiento visual para videos cortos.

Pipeline (replica Proceso 3 largo adaptado a cortos):
  1. segment  : Lee SRT word-level de P2 Corto → extrae subtítulos nivel-oración
  2. enrich   : Copiar prompt → pegar en Gemini chat → pegar JSON de vuelta
               Gemini agrupa oraciones en escenas Y asigna visuales (LIBERTAD TOTAL)
  3. timeline : Combina batches

Flujo: COPY-PASTE manual (no API de Gemini).
Reutiliza funciones de sentence extraction del Proceso 3 largo.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app, send_file, make_response
from pathlib import Path
import json
import logging
import time

from aplicacion import db
from aplicacion.models.proceso1_corto import Proceso1CortoJob
from aplicacion.models.proceso2_corto import Proceso2CortoSubprocessState
from aplicacion.models.proceso3_corto import Proceso3CortoJob, Proceso3CortoSubprocessState

# Reutilizar utilidades del Proceso 3 largo
from aplicacion.endpoints.proceso3 import (
	_parse_json_array,
	_validate_and_normalize_scenes,
	_is_sentence_end,
	_flatten_segment_words,
	_build_subtitle_text,
)


proceso3_corto_bp = Blueprint('proceso3_corto', __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_workspace_data_dir() -> Path:
	return Path(__file__).resolve().parents[4] / 'data'


def get_job_dir(job_id: int) -> Path:
	return get_workspace_data_dir() / 'proceso3_corto' / str(job_id)


def get_or_create_job(job_id: int) -> Proceso3CortoJob:
	Proceso1CortoJob.query.get_or_404(job_id)
	job = Proceso3CortoJob.query.get(job_id)
	if job is None:
		job = Proceso3CortoJob(proceso1_corto_job_id=job_id)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(job_id: int, subprocess_key: str) -> Proceso3CortoSubprocessState:
	state = Proceso3CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso3CortoSubprocessState(proceso1_corto_job_id=job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state


def _save_state(state: Proceso3CortoSubprocessState, payload: dict) -> Proceso3CortoSubprocessState:
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


# ─────────────────────────────────────────────────────────────────────────────
# CRUD endpoints
# ─────────────────────────────────────────────────────────────────────────────

@proceso3_corto_bp.route('/jobs/<int:job_id>/init', methods=['POST'])
def init_job(job_id: int):
	job = get_or_create_job(job_id)
	job_dir = get_job_dir(job_id)
	(job_dir / 'input').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso3_corto_bp.route('/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id: int):
	job = get_or_create_job(job_id)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/<string:subprocess_key>', methods=['GET'])
def get_subprocess_state(job_id: int, subprocess_key: str):
	get_or_create_job(job_id)
	state = get_or_create_subprocess_state(job_id, subprocess_key)
	db.session.commit()
	return jsonify(state.to_dict())


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses', methods=['GET'])
def list_subprocess_states(job_id: int):
	get_or_create_job(job_id)
	states = (
		Proceso3CortoSubprocessState.query
		.filter_by(proceso1_corto_job_id=job_id)
		.order_by(Proceso3CortoSubprocessState.updated_at.asc())
		.all()
	)
	return jsonify([s.to_dict() for s in states])


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/<string:subprocess_key>', methods=['PUT'])
def save_subprocess_state(job_id: int, subprocess_key: str):
	get_or_create_job(job_id)
	state = get_or_create_subprocess_state(job_id, subprocess_key)
	payload = request.get_json(silent=True) or {}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: SEGMENT — Extrae subtítulos nivel-ORACIÓN del SRT word-level
# Igual que P3 largo pero sin markers/secciones. Una sola sección: 'full'.
# Usa _segments.json (word-level timestamps) de P2 Corto.
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sentence_subtitles_corto(all_words: list[dict]) -> list[dict]:
	"""Extrae subtítulos nivel-oración desde word-level timestamps.
	Idéntico a P3 largo pero sin secciones. Cada oración = 1 subtítulo."""
	if not all_words:
		return []

	sentences: list[list[dict]] = []
	buf: list[dict] = []
	for w in all_words:
		buf.append(w)
		if _is_sentence_end(w.get('word', '')):
			sentences.append(buf)
			buf = []
	if buf:
		sentences.append(buf)

	subtitles: list[dict] = []
	for i, group in enumerate(sentences, start=1):
		if not group:
			continue
		text = _build_subtitle_text(group)
		if not text:
			continue
		start_t = float(group[0].get('start', 0))
		end_t = float(group[-1].get('end', 0))
		subtitles.append({
			'num': i,
			'section': 'full',
			'start': round(start_t, 3),
			'end': round(end_t, 3),
			'text': text,
			'duration': round(end_t - start_t, 2),
		})
	return subtitles


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/segment/run', methods=['POST'])
def run_segment(job_id: int):
	"""Extrae subtítulos nivel-oración del SRT word-level de P2 Corto.
	Gemini después decidirá cómo agrupar estos en escenas (paso Enrich)."""
	get_or_create_job(job_id)

	# Load SRT data from Proceso 2 Corto
	srt_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='srt',
	).first()

	if not srt_state or srt_state.status != 'completed':
		return jsonify({'error': 'Primero completa Proceso 2 Corto: SRT'}), 400

	srt_output = srt_state.output_payload or {}
	srt_path_value = srt_output.get('srtPath')

	if not srt_path_value:
		return jsonify({'error': 'No se encontró srtPath en Proceso 2 Corto'}), 400

	srt_path = Path(str(srt_path_value))
	if not srt_path.exists():
		return jsonify({'error': f'No se encontró SRT en: {srt_path}'}), 400

	# Prefer word-level timestamps from _segments.json
	segments_json_path = Path(str(srt_path).replace('.srt', '_segments.json'))
	all_words: list[dict] | None = None

	if segments_json_path.exists():
		raw_segments = json.loads(segments_json_path.read_text(encoding='utf-8'))
		all_words = _flatten_segment_words(raw_segments)

	# Fallback: parse SRT segments
	if not all_words:
		from aplicacion.endpoints.proceso2.core.srt_generator import parse_srt_file
		srt_segments = parse_srt_file(str(srt_path))
		if not srt_segments:
			return jsonify({'error': 'No se encontraron segmentos en el SRT ni en _segments.json'}), 400
		all_words = [
			{'word': s['text'], 'start': s['start'], 'end': s['end']}
			for s in srt_segments if s.get('text', '').strip()
		]

	subtitles = _extract_sentence_subtitles_corto(all_words)
	if not subtitles:
		return jsonify({'error': 'No se pudieron extraer oraciones del SRT'}), 400

	subtitles_by_section = {'full': subtitles}

	job_dir = get_job_dir(job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	subtitles_path = output_dir / 'subtitles_by_section.json'
	subtitles_path.write_text(json.dumps(subtitles_by_section, ensure_ascii=False, indent=2), encoding='utf-8')

	stats = {
		'totalSubtitles': len(subtitles),
		'sections': {'full': len(subtitles)},
		'source': 'word_level' if segments_json_path.exists() else 'srt_fallback',
	}

	state = get_or_create_subprocess_state(job_id, 'segment')
	payload = {
		'status': 'completed',
		'input': {
			'srtPath': str(srt_path),
			'segmentsJsonPath': str(segments_json_path) if segments_json_path.exists() else None,
		},
		'output': {
			'subtitlesPath': str(subtitles_path),
			'subtitles': subtitles,
			'subtitlesBySection': subtitles_by_section,
			'stats': stats,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: ENRICH — Copiar prompt → Pegar en Gemini → Pegar JSON de vuelta
# Gemini tiene LIBERTAD TOTAL de agrupar oraciones en escenas como quiera.
# Puede crear 15, 17, 20 escenas — lo que tenga sentido para el contenido.
# ─────────────────────────────────────────────────────────────────────────────

def _gemini_enrich_prompt_corto(subtitles: list[dict], context: dict | None = None) -> str:
	"""Prompt para videos cortos — Gemini AGRUPA oraciones en escenas Y asigna visuales.
	Libertad total de decidir cuántas escenas crear (igual que P3 largo)."""
	visual_types = ["Animation", "Graphic", "B-roll", "Stock", "Text", "Screen Recording"]

	ctx = context or {}
	tema_principal = str(ctx.get('tema_principal') or '').strip()

	context_block = ''
	if tema_principal:
		context_block = f'VIDEO TOPIC: {tema_principal}\n\n'

	system = (
		"ROLE: Visual Director for SHORT-FORM vertical videos (TikTok, YouTube Shorts, Reels).\n"
		"You will receive sentence-level subtitles from a short video (under 2 minutes).\n"
		"Each subtitle has: num, start, end, text.\n\n"
		+ context_block
		+ "YOUR TASK:\n"
		"1. GROUP the subtitles into scenes. Each scene is a coherent visual unit (3-6 seconds ideal for shorts).\n"
		"   - Combine subtitles that deal with the SAME visual concept.\n"
		"   - Separate when the image the viewer should see changes.\n"
		"   - A scene can contain 1, 2, or 3 subtitles — whatever makes visual sense.\n"
		"   - The scene text is the concatenation of the subtitles it groups.\n"
		"   - start = start of the first subtitle in the group; end = end of the last.\n"
		"   - You decide HOW MANY scenes to create. Could be more or fewer than input subtitles.\n\n"
		"2. For each scene, decide:\n"
		f"   - visual_type: exactly one of [{', '.join(visual_types)}]\n"
		"   - visual_description: brief 1-line description of the ideal visual.\n"
		"     Be ULTRA SPECIFIC — not 'a planet' but 'Jupiter's Great Red Spot rotating slowly'.\n"
		"     Target audience is American, use US customary units naturally.\n\n"
		"3. For each scene, extract physical_composition:\n"
		"   List the REAL, LITERAL physical objects and materials shown.\n"
		"   NO metaphors, NO sci-fi, NO abstract art.\n"
		"   Only real objects a VFX team would use as reference.\n\n"
		"Reply ONLY with a JSON array. Each element:\n"
		"{\n"
		'  "scene_num": N,\n'
		'  "section": "full",\n'
		'  "start": first_start_of_the_group,\n'
		'  "end": last_end_of_the_group,\n'
		'  "text": "concatenated text of the grouped subtitles",\n'
		'  "duration": end - start,\n'
		'  "visual_type": "...",\n'
		'  "visual_description": "...",\n'
		'  "physical_composition": "real physical objects list"\n'
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
	return f"{system}\n\nSubtitles of the video:\n{subs_json}"


def _get_proceso1_corto_context(job_id: int) -> dict:
	"""Load context from Proceso 1 Corto for enrichment."""
	try:
		from aplicacion.models.proceso1_corto import Proceso1CortoJob as P1CJ
		job = P1CJ.query.get(job_id)
		if not job:
			return {}
		return {'tema_principal': job.video_id or ''}
	except Exception:
		return {}


def _get_segment_subtitles(job_id: int) -> list[dict]:
	"""Get subtitles from the segment step."""
	segment_state = Proceso3CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='segment',
	).first()
	if not segment_state or not (segment_state.output_payload or {}).get('subtitlesBySection'):
		raise ValueError('Primero ejecuta Proceso 3 Corto: Segment')

	subtitles_by_section = (segment_state.output_payload or {}).get('subtitlesBySection') or {}
	subtitles = subtitles_by_section.get('full') or []
	if not subtitles:
		raise ValueError('No hay subtítulos para enriquecer')
	return subtitles


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/enrich/prompt', methods=['GET'])
def get_enrich_prompt(job_id: int):
	"""Returns the prompt to copy-paste into Gemini chat."""
	get_or_create_job(job_id)
	try:
		subtitles = _get_segment_subtitles(job_id)
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400

	video_context = _get_proceso1_corto_context(job_id)
	prompt = _gemini_enrich_prompt_corto(subtitles, context=video_context)
	return jsonify({
		'section': 'full',
		'subtitleCount': len(subtitles),
		'prompt': prompt,
	})


@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/enrich/manual', methods=['POST'])
def save_manual_enrich(job_id: int):
	"""Save manually pasted Gemini response (copy-paste workflow)."""
	get_or_create_job(job_id)
	body = request.get_json(silent=True) or {}

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
			return jsonify({'error': f'No se pudo parsear el JSON: {str(exc)}'}), 400

	try:
		normalized = _validate_and_normalize_scenes(scenes, 'full')
		for i, scene in enumerate(normalized):
			scene['scene_num'] = i + 1

		# Save batch
		job_dir = get_job_dir(job_id)
		batches_dir = job_dir / 'output' / 'batches'
		batches_dir.mkdir(parents=True, exist_ok=True)
		batch_path = batches_dir / 'batch_full.json'
		batch_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')

		state = get_or_create_subprocess_state(job_id, 'batch_full')
		metadata: dict = {}
		if raw_response is not None:
			metadata['rawResponse'] = str(raw_response)
		if prompt_used is not None:
			metadata['promptUsed'] = str(prompt_used)

		payload = {
			'status': 'completed',
			'input': {'section': 'full'},
			'output': {
				'batchPath': str(batch_path),
				'scenes': normalized,
				'sceneCount': len(normalized),
			},
			'metadata': metadata,
		}
		saved = _save_state(state, payload)
		return jsonify(saved.to_dict())
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: TIMELINE — Combina batches enriquecidos
# ─────────────────────────────────────────────────────────────────────────────

@proceso3_corto_bp.route('/jobs/<int:job_id>/subprocesses/timeline/run', methods=['POST'])
def run_timeline(job_id: int):
	get_or_create_job(job_id)

	batch_states = Proceso3CortoSubprocessState.query.filter(
		Proceso3CortoSubprocessState.proceso1_corto_job_id == job_id,
		Proceso3CortoSubprocessState.subprocess_key.like('batch_%'),
	).all()

	scenes: list[dict] = []
	for st in batch_states:
		batch_scenes = (st.output_payload or {}).get('scenes')
		if isinstance(batch_scenes, list):
			scenes.extend(batch_scenes)

	if not scenes:
		return jsonify({'error': 'No hay escenas enriquecidas. Pega el JSON de Gemini primero.'}), 400

	scenes.sort(key=lambda s: float(s.get('start', 0.0)))
	for i, scene in enumerate(scenes):
		scene['scene_num'] = i + 1

	timeline = {
		'proceso1CortoJobId': job_id,
		'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
		'batches': sorted([st.subprocess_key for st in batch_states]),
		'scenes': scenes,
	}

	job_dir = get_job_dir(job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	timeline_path = output_dir / 'timeline.json'
	timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')

	state = get_or_create_subprocess_state(job_id, 'timeline')
	payload = {
		'status': 'completed',
		'input': {'source': 'batch_full'},
		'output': {
			'timelinePath': str(timeline_path),
			'timeline': timeline,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
# Audio serving (from Proceso 2 Corto)
# ─────────────────────────────────────────────────────────────────────────────

def _get_audio_path_from_p2_corto(job_id: int) -> Path | None:
	speed_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='speed',
	).first()
	if speed_state and speed_state.output_payload:
		file_path = speed_state.output_payload.get('filePath')
		if file_path:
			p = Path(str(file_path))
			if p.exists():
				return p
	audio_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='audio_input',
	).first()
	if audio_state and audio_state.output_payload:
		file_path = audio_state.output_payload.get('filePath')
		if file_path:
			p = Path(str(file_path))
			if p.exists():
				return p
	return None


@proceso3_corto_bp.route('/jobs/<int:job_id>/audio', methods=['GET'])
def get_job_audio(job_id: int):
	get_or_create_job(job_id)
	path = _get_audio_path_from_p2_corto(job_id)
	if not path:
		return jsonify({'error': 'No se encontró audio. Ejecuta Proceso 2 Corto primero.'}), 400
	return send_file(str(path), mimetype='audio/mpeg', as_attachment=False, conditional=True)



# ─────────────────────────────────────────────────────────────────────────────
# SUBTITLES — Genera SRT optimizado para video corto vertical
# Usa word-level timestamps de Proceso 2 Corto (final_segments.json)
# ─────────────────────────────────────────────────────────────────────────────

@proceso3_corto_bp.route('/jobs/<int:job_id>/generate-subtitles', methods=['POST'])
def generate_subtitles(job_id: int):
	"""Genera SRT optimizado para videos cortos verticales.

	Lee final_segments.json (word-level timestamps) de Proceso 2 Corto,
	aplica chunking inteligente (max ~42 chars por línea), y genera un SRT
	perfecto para pantalla vertical (9:16).

	Body (optional):
	  - maxChars: int (default 42) — max characters per subtitle line
	"""
	get_or_create_job(job_id)
	body = request.get_json(silent=True) or {}
	max_chars = int(body.get('maxChars') or 42)

	from .core.subtitle_generator_corto import (
		generate_subtitles_from_segments,
		export_srt,
		get_subtitle_stats,
	)

	# Find word-level segments from Proceso 2 Corto
	srt_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='srt',
	).first()

	if not srt_state or srt_state.status != 'completed':
		return jsonify({'error': 'Primero completa Proceso 2 Corto: SRT'}), 400

	srt_output = srt_state.output_payload or {}
	srt_path_value = srt_output.get('srtPath')

	if not srt_path_value:
		return jsonify({'error': 'No se encontró srtPath en Proceso 2 Corto'}), 400

	srt_path = Path(str(srt_path_value))
	segments_json_path = Path(str(srt_path).replace('.srt', '_segments.json'))

	segments = None
	source = 'unknown'

	# Prefer word-level segments (has per-word timestamps)
	if segments_json_path.exists():
		try:
			segments = json.loads(segments_json_path.read_text(encoding='utf-8'))
			source = 'word_level'
		except Exception as e:
			logger.warning(f'Could not parse segments JSON: {e}')

	# Fallback: parse SRT (sentence-level only, less precise)
	if not segments:
		if srt_path.exists():
			from aplicacion.endpoints.proceso2.core.srt_generator import parse_srt_file
			parsed = parse_srt_file(str(srt_path))
			if parsed:
				segments = parsed
				source = 'srt_fallback'

	if not segments:
		return jsonify({'error': 'No se encontraron segmentos de audio. Ejecuta Whisper en P2 Corto primero.'}), 400

	# Generate chunked subtitles
	subtitles = generate_subtitles_from_segments(segments, max_chars=max_chars)
	if not subtitles:
		return jsonify({'error': 'No se pudieron generar subtítulos del audio'}), 400

	stats = get_subtitle_stats(subtitles)

	# Save SRT file
	job_dir = get_job_dir(job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	srt_output_path = output_dir / 'subtitles.srt'
	export_srt(subtitles, str(srt_output_path))

	# Also save as JSON for frontend preview
	json_output_path = output_dir / 'subtitles.json'
	json_output_path.write_text(
		json.dumps(subtitles, ensure_ascii=False, indent=2),
		encoding='utf-8',
	)

	# Save state
	state = get_or_create_subprocess_state(job_id, 'subtitles')
	payload = {
		'status': 'completed',
		'input': {
			'maxChars': max_chars,
			'source': source,
			'segmentsJsonPath': str(segments_json_path) if segments_json_path.exists() else None,
		},
		'output': {
			'srtPath': str(srt_output_path),
			'jsonPath': str(json_output_path),
			'subtitles': subtitles,
			'stats': stats,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso3_corto_bp.route('/jobs/<int:job_id>/subtitles.srt', methods=['GET'])
def download_subtitles_srt(job_id: int):
	"""Sirve el archivo SRT generado para descarga/uso en render."""
	get_or_create_job(job_id)

	job_dir = get_job_dir(job_id)
	srt_path = job_dir / 'output' / 'subtitles.srt'

	if not srt_path.exists():
		return jsonify({'error': 'No se ha generado un SRT aún. Usa POST /generate-subtitles primero.'}), 404

	response = make_response(srt_path.read_text(encoding='utf-8'))
	response.headers['Content-Type'] = 'text/plain; charset=utf-8'
	response.headers['Content-Disposition'] = f'attachment; filename="subtitles_{job_id}.srt"'
	return response


@proceso3_corto_bp.route('/jobs/<int:job_id>/subtitles', methods=['GET'])
def get_subtitles(job_id: int):
	"""Retorna los subtítulos generados en formato JSON para preview en el frontend."""
	get_or_create_job(job_id)

	state = Proceso3CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id,
		subprocess_key='subtitles',
	).first()

	if not state or state.status != 'completed':
		return jsonify({'subtitles': [], 'generated': False})

	output = state.output_payload or {}
	return jsonify({
		'subtitles': output.get('subtitles', []),
		'stats': output.get('stats', {}),
		'generated': True,
	})


__all__ = ['proceso3_corto_bp']

