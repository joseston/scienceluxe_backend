from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1SubprocessState
from aplicacion.models.proceso2 import Proceso2SubprocessState
from aplicacion.models.proceso3 import Proceso3SubprocessState
from aplicacion.models.proceso4 import Proceso4SubprocessState
from aplicacion.models.proceso5 import Proceso5Job, Proceso5SubprocessState
from .prompt_templates import (
	build_metadata_prompt,
	build_thumbnail_prompt_for_external_ai,
	build_title_prompt_for_opus,
)

proceso5_bp = Blueprint('proceso5', __name__)
logger = logging.getLogger(__name__)

def get_workspace_data_dir() -> Path:
	return Path(__file__).resolve().parents[4] / 'data'

def get_job_dir(proceso1_job_id: int) -> Path:
	return get_workspace_data_dir() / 'proceso5' / str(proceso1_job_id)

def get_or_create_job(proceso1_job_id: int) -> Proceso5Job:
	Proceso1Job.query.get_or_404(proceso1_job_id)
	job = Proceso5Job.query.get(proceso1_job_id)
	if job is None:
		job = Proceso5Job(proceso1_job_id=proceso1_job_id)
		db.session.add(job)
	return job

def get_or_create_subprocess_state(proceso1_job_id: int, subprocess_key: str) -> Proceso5SubprocessState:
	state = Proceso5SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso5SubprocessState(proceso1_job_id=proceso1_job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state

def _save_state(state: Proceso5SubprocessState, payload: dict) -> Proceso5SubprocessState:
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

@proceso5_bp.route('/jobs/<int:proceso1_job_id>/init', methods=['POST'])
def init_proceso5_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	job_dir = get_job_dir(proceso1_job_id)
	job_dir.mkdir(parents=True, exist_ok=True)
	db.session.commit()
	return jsonify(job.to_dict())

@proceso5_bp.route('/jobs/<int:proceso1_job_id>', methods=['GET'])
def get_proceso5_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	db.session.commit()
	return jsonify(job.to_dict())

@proceso5_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['GET'])
def get_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	db.session.commit()
	return jsonify(state.to_dict())

@proceso5_bp.route('/jobs/<int:proceso1_job_id>/subprocesses', methods=['GET'])
def list_subprocess_states(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	states = (
		Proceso5SubprocessState.query
		.filter_by(proceso1_job_id=proceso1_job_id)
		.order_by(Proceso5SubprocessState.updated_at.asc())
		.all()
	)
	return jsonify([s.to_dict() for s in states])

@proceso5_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['PUT'])
def save_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	payload = request.get_json(silent=True) or {}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())

def _call_gemini(prompt: str) -> str:
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
	if not api_key:
		from config import GEMINI_API_KEY, GEMINI_MODEL
		api_key = GEMINI_API_KEY
		model_name = GEMINI_MODEL
		
	if not api_key:
		raise RuntimeError('GEMINI_API_KEY no está configurada en el backend')

	try:
		import google.generativeai as genai
	except ImportError as exc:
		raise RuntimeError('Falta dependencia: pip install google-generativeai') from exc

	genai.configure(api_key=api_key)
	model = genai.GenerativeModel(model_name)
	resp = model.generate_content(prompt)
	return resp.text or ''

def _parse_json_dict(raw_text: str) -> dict:
	import re
	match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text)
	if not match:
		match = re.search(r"```\s*([\s\S]*?)\s*```", raw_text)
	json_str = match.group(1) if match else raw_text
	try:
		return json.loads(json_str)
	except Exception:
		return json.loads(json_str.strip())


def _load_final_script(pid: int) -> str:
	# Fuente oficial: subproceso5_final.scriptFinal (guion ensamblado al final del Proceso 1)
	sp5_final = Proceso1SubprocessState.query.filter_by(
		job_id=pid, subprocess_key='subproceso5_final'
	).first()

	script_text = ""
	if sp5_final and sp5_final.output_payload:
		script_text = str((sp5_final.output_payload or {}).get('scriptFinal', '') or '')

	# Fallback: subproceso2.guion_texto (compatibilidad con proyectos antiguos)
	if not script_text.strip():
		p1_state = Proceso1SubprocessState.query.filter_by(
			job_id=pid, subprocess_key='subproceso2'
		).first()
		if p1_state and p1_state.output_payload:
			guion_data = (p1_state.output_payload or {}).get('guion', {})
			script_text = str((guion_data or {}).get('guion_texto', '') or '')

	# Fallback final: sesión en disco
	if not script_text.strip():
		session_path = get_workspace_data_dir() / 'projects' / f'{pid}_session.json'
		if session_path.exists():
			try:
				sess = json.loads(session_path.read_text(encoding='utf-8'))
				script_text = str(sess.get('p2_guion_texto', '') or '')
			except Exception:
				pass

	return script_text.strip()


def _load_subtemas(pid: int) -> list[str]:
	subtemas: list[str] = []

	try:
		p1_state = Proceso1SubprocessState.query.filter_by(
			job_id=pid, subprocess_key='subproceso2'
		).first()
		if p1_state and p1_state.output_payload:
			estructura = (p1_state.output_payload or {}).get('estructura', {})
			for subtema in estructura.get('subtemas', []):
				titulo = (subtema.get('titulo', '') if isinstance(subtema, dict) else str(subtema)).strip()
				if titulo:
					subtemas.append(titulo)
	except Exception:
		pass

	if subtemas:
		return subtemas

	session_path = get_workspace_data_dir() / 'projects' / f'{pid}_session.json'
	if session_path.exists():
		try:
			sess = json.loads(session_path.read_text(encoding='utf-8'))
			estructura = sess.get('p2_estructura') or {}
			for subtema in estructura.get('subtemas', []):
				titulo = (subtema.get('titulo', '') if isinstance(subtema, dict) else str(subtema)).strip()
				if titulo:
					subtemas.append(titulo)
		except Exception:
			pass

	return subtemas


def _normalize_section_key(label: str) -> str:
	normalized = (label or '').strip().lower()
	mapping = {
		'parte1': 'subtema_1',
		'parte2': 'subtema_2',
		'parte3': 'subtema_3',
		'parte4': 'subtema_4',
		'parte4_cierre': 'cierre',
		'subtema1': 'subtema_1',
		'subtema2': 'subtema_2',
		'subtema3': 'subtema_3',
		'subtema4': 'subtema_4',
		'closing': 'cierre',
		'outro': 'cierre',
	}
	return mapping.get(normalized, normalized)


def _load_timeline_scenes(pid: int) -> list[dict]:
	for model, key_field in ((Proceso4SubprocessState, 'proceso1_job_id'), (Proceso3SubprocessState, 'proceso1_job_id')):
		state = model.query.filter_by(**{key_field: pid, 'subprocess_key': 'import_timeline' if model is Proceso4SubprocessState else 'timeline'}).first()
		if state and state.output_payload:
			timeline = (state.output_payload or {}).get('timeline') or {}
			scenes = timeline.get('scenes') or []
			if isinstance(scenes, list) and scenes:
				return sorted(scenes, key=lambda scene: float(scene.get('start', 0.0) or 0.0))
	return []


def _load_auto_indice_output(pid: int) -> dict:
	state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='auto_indice',
	).first()
	if state and isinstance(state.output_payload, dict):
		return state.output_payload or {}
	return {}


def _load_concat_markers(pid: int) -> dict:
	state = Proceso2SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='concat',
	).first()
	if state and isinstance(state.output_payload, dict):
		return (state.output_payload or {}).get('markers') or {}
	return {}


def _format_timestamp(seconds: float) -> str:
	total_seconds = max(0, int(float(seconds or 0)))
	hours, remainder = divmod(total_seconds, 3600)
	minutes, secs = divmod(remainder, 60)
	if hours > 0:
		return f'{hours:02d}:{minutes:02d}:{secs:02d}'
	return f'{minutes:02d}:{secs:02d}'


def _build_timeline_entries(pid: int, subtemas: list[str]) -> list[dict]:
	scenes = _load_timeline_scenes(pid)
	auto_indice = _load_auto_indice_output(pid)
	markers = _load_concat_markers(pid)

	section_starts: dict[str, float] = {}
	for scene in scenes:
		section = _normalize_section_key(str(scene.get('section', '') or ''))
		if not section:
			continue
		start = float(scene.get('start', 0.0) or 0.0)
		section_starts.setdefault(section, start)

	if not section_starts and isinstance(markers, dict):
		for raw_key, marker in markers.items():
			if not isinstance(marker, dict) or raw_key.startswith('_'):
				continue
			section = _normalize_section_key(raw_key)
			section_starts.setdefault(section, float(marker.get('start', 0.0) or 0.0))

	entries: list[dict] = []
	index_start = auto_indice.get('start')
	if index_start is not None:
		index_start = float(index_start or 0.0)

	if index_start is None or index_start > 0:
		entries.append({'time': 0.0, 'label': 'Intro'})

	if index_start is not None:
		entries.append({'time': index_start, 'label': 'Index'})

	subtopic_indexes = {
		int(section_key.split('_')[-1])
		for section_key in section_starts
		if section_key.startswith('subtema_') and section_key.split('_')[-1].isdigit()
	}
	max_subtopics = max(subtopic_indexes | set(range(1, len(subtemas) + 1)), default=0)

	for idx in range(1, max_subtopics + 1):
		section_key = f'subtema_{idx}'
		if section_key in section_starts:
			label = subtemas[idx - 1] if idx - 1 < len(subtemas) else f'Subtopic {idx}'
			entries.append({'time': section_starts[section_key], 'label': label})

	if 'cierre' in section_starts:
		entries.append({'time': section_starts['cierre'], 'label': 'Closing'})

	if not entries:
		entries.append({'time': 0.0, 'label': 'Intro'})

	entries.sort(key=lambda item: (float(item['time']), 0 if item['label'] in {'Intro', 'Index'} else 1, item['label']))

	unique_entries: list[dict] = []
	seen = set()
	for entry in entries:
		timestamp = _format_timestamp(entry['time'])
		label = str(entry['label']).strip() or 'Section'
		key = (timestamp, label.lower())
		if key in seen:
			continue
		seen.add(key)
		unique_entries.append({'time': float(entry['time']), 'timestamp': timestamp, 'label': label})

	return unique_entries


def _build_timeline_lines(pid: int, subtemas: list[str]) -> list[str]:
	entries = _build_timeline_entries(pid, subtemas)
	return [f"{entry['timestamp']} {entry['label']}" for entry in entries]


def _compose_description(description_body: str, timeline_lines: list[str]) -> str:
	parts: list[str] = []
	body = (description_body or '').strip()
	if body:
		parts.append(body)
	if timeline_lines:
		parts.append('Timeline\n' + '\n'.join(timeline_lines))
	return '\n\n'.join(parts).strip()


def _get_existing_output(state: Proceso5SubprocessState) -> dict:
	if isinstance(state.output_payload, dict):
		return dict(state.output_payload or {})
	return {}


@proceso5_bp.route('/jobs/<int:pid>/metadata/generate', methods=['POST'])
def generate_metadata(pid: int):
	"""Genera solo el prompt de títulos para Opus."""
	get_or_create_job(pid)

	script_text = _load_final_script(pid)
	subtemas = _load_subtemas(pid)
	timeline_lines = _build_timeline_lines(pid, subtemas)

	if not script_text.strip():
		return jsonify({
			'error': (
				'No se encontró el guion final del proyecto. '
				'Asegúrate de haber completado el Proceso 1 hasta el Subproceso 5 (cierre y ensamblado del guion final).'
			)
		}), 400

	state = get_or_create_subprocess_state(pid, 'metadata_generation')
	_save_state(state, {'status': 'running'})

	try:
		existing_output = _get_existing_output(state)
		title_prompt = build_title_prompt_for_opus(script_text, subtemas, timeline_lines)

		payload = {
			'status': 'completed',
			'output': {
				**existing_output,
				'title_prompt': title_prompt,
				'selected_title': str(existing_output.get('selected_title', '') or '').strip(),
			},
			'metadata': {
				**(state.metadata_payload or {}),
				'timelineLines': timeline_lines,
			},
		}
		saved = _save_state(state, payload)
		return jsonify(saved.to_dict())
	except Exception as e:
		_save_state(state, {
			'status': 'error',
			'metadata': {'error': str(e)}
		})
		return jsonify({'error': f'Error generando prompt de títulos: {str(e)}'}), 500


@proceso5_bp.route('/jobs/<int:pid>/metadata/generate-assets', methods=['POST'])
def generate_metadata_assets(pid: int):
	"""Genera thumbnail, descripción y keywords usando el título final elegido."""
	get_or_create_job(pid)

	script_text = _load_final_script(pid)
	subtemas = _load_subtemas(pid)
	timeline_lines = _build_timeline_lines(pid, subtemas)

	if not script_text.strip():
		return jsonify({
			'error': (
				'No se encontró el guion final del proyecto. '
				'Asegúrate de haber completado el Proceso 1 hasta el Subproceso 5 (cierre y ensamblado del guion final).'
			)
		}), 400

	state = get_or_create_subprocess_state(pid, 'metadata_generation')
	payload = request.get_json(silent=True) or {}
	existing_output = _get_existing_output(state)
	selected_title = str(
		payload.get('selected_title')
		or existing_output.get('selected_title')
		or ''
	).strip()

	if not selected_title:
		return jsonify({'error': 'Primero debes elegir o pegar un título final antes de generar thumbnail y descripción.'}), 400

	_save_state(state, {'status': 'running'})

	try:
		prompt = build_metadata_prompt(script_text, selected_title, subtemas, timeline_lines)
		thumbnail_prompt = build_thumbnail_prompt_for_external_ai(
			script_text,
			selected_title,
			subtemas,
			timeline_lines,
		)
		raw = _call_gemini(prompt)
		metadata = _parse_json_dict(raw)
		
		# Validation
		if not isinstance(metadata, dict):
			raise ValueError("LLM did not return a valid JSON object.")

		description_body = str(metadata.get('description_body') or metadata.get('descripcion') or '').strip()
		keywords = metadata.get('keywords', [])
		if not isinstance(keywords, list):
			keywords = [str(keywords)] if str(keywords).strip() else []
		descripcion = _compose_description(description_body, timeline_lines)
			
		payload = {
			'status': 'completed',
			'output': {
				**existing_output,
				'title_prompt': str(existing_output.get('title_prompt', '') or '').strip(),
				'selected_title': selected_title,
				'descripcion': descripcion,
				'keywords': keywords,
				'thumbnail_prompt': thumbnail_prompt,
			},
			'metadata': {
				**(state.metadata_payload or {}),
				'rawResponse': raw,
				'timelineLines': timeline_lines,
				'descriptionBody': description_body,
				'selectedTitle': selected_title,
			},
		}
		saved = _save_state(state, payload)
		return jsonify(saved.to_dict())
	except Exception as e:
		_save_state(state, {
			'status': 'error',
			'metadata': {'error': str(e)}
		})
		return jsonify({'error': f'Error generando metadatos: {str(e)}'}), 500
