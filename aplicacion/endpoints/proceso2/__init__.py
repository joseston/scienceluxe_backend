from __future__ import annotations

from flask import Blueprint, jsonify, request
from pathlib import Path
import json
import sys

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job
from aplicacion.models.proceso2 import Proceso2Job, Proceso2SubprocessState
from config import STORAGE_ROOT as STORAGE_ROOT_CONFIG


proceso2_bp = Blueprint('proceso2', __name__)


def ensure_workspace_imports():
	workspace_root = Path(__file__).resolve().parents[4]
	workspace_root_str = str(workspace_root)
	if workspace_root_str not in sys.path:
		sys.path.append(workspace_root_str)


# Raíz de almacenamiento persistente en disco externo/local
STORAGE_ROOT = Path(STORAGE_ROOT_CONFIG)


def _get_video_id(proceso1_job_id: int) -> str:
	"""Devuelve el video_id del Proceso1Job, o el ID numérico como fallback."""
	try:
		job = Proceso1Job.query.get(proceso1_job_id)
		if job and job.video_id:
			# Sanitizar: sólo alfanuméricos, guiones y guiones bajos
			import re
			return re.sub(r'[^A-Za-z0-9_\-]', '_', job.video_id)[:60]
		return str(proceso1_job_id)
	except Exception:
		return str(proceso1_job_id)


def get_job_dir(proceso1_job_id: int) -> Path:
	# {STORAGE_ROOT}/job_<id>_<video_id>/
	video_id = _get_video_id(proceso1_job_id)
	return STORAGE_ROOT / f'job_{proceso1_job_id}_{video_id}'


def get_or_create_job(proceso1_job_id: int) -> Proceso2Job:
	# Ensure Proceso 1 job exists
	Proceso1Job.query.get_or_404(proceso1_job_id)

	job = Proceso2Job.query.get(proceso1_job_id)
	if job is None:
		job = Proceso2Job(proceso1_job_id=proceso1_job_id)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(proceso1_job_id: int, subprocess_key: str) -> Proceso2SubprocessState:
	state = Proceso2SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso2SubprocessState(proceso1_job_id=proceso1_job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state


def _save_state(state: Proceso2SubprocessState, payload: dict) -> Proceso2SubprocessState:
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


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/init', methods=['POST'])
def init_proceso2_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	job_dir = get_job_dir(proceso1_job_id)
	(job_dir / 'input').mkdir(parents=True, exist_ok=True)
	(job_dir / 'work').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>', methods=['GET'])
def get_proceso2_job(proceso1_job_id: int):
	job = get_or_create_job(proceso1_job_id)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['GET'])
def get_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	db.session.commit()
	return jsonify(state.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/<string:subprocess_key>', methods=['PUT'])
def save_subprocess_state(proceso1_job_id: int, subprocess_key: str):
	get_or_create_job(proceso1_job_id)
	state = get_or_create_subprocess_state(proceso1_job_id, subprocess_key)
	payload = request.get_json(silent=True) or {}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/whisper/status', methods=['GET'])
def whisper_status():
	from .core.srt_generator import check_whisper_status

	return jsonify(check_whisper_status())


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline endpoints
# Keys used in Proceso2SubprocessState:
#   - audio_input
#   - speed
#   - concat
#   - srt
#   - scenes
# ─────────────────────────────────────────────────────────────────────────────


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/audio_input/upload', methods=['POST'])
def upload_audio_parts(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)

	required_fields = ['intro', 'parte1', 'parte2', 'parte3', 'parte4', 'cierre']
	missing = [f for f in required_fields if f not in request.files]
	if missing:
		return jsonify({'error': f'Faltan archivos: {", ".join(missing)}'}), 400

	from .core.audio_processor import get_audio_duration

	job_dir = get_job_dir(proceso1_job_id)
	input_dir = job_dir / 'input'
	input_dir.mkdir(parents=True, exist_ok=True)

	allowed_ext = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}

	saved_paths: dict[str, str] = {}
	durations: dict[str, float] = {}
	for field in required_fields:
		f = request.files[field]

		original_name = (f.filename or '').strip()
		ext = Path(original_name).suffix.lower() if original_name else ''
		if ext not in allowed_ext:
			# Default to wav if unknown/no extension; ffmpeg/pydub will usually still read it.
			ext = '.wav'

		out_path = input_dir / f'{field}{ext}'
		f.save(out_path)
		saved_paths[field] = str(out_path)
		durations[field] = float(get_audio_duration(str(out_path)) or 0)

	state = get_or_create_subprocess_state(proceso1_job_id, 'audio_input')
	payload = {
		'status': 'completed',
		'input': {
			'files': saved_paths,
		},
		'output': {
			'durations': durations,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/audio_input/replace', methods=['PATCH'])
def replace_audio_part(proceso1_job_id: int):
	"""Reemplaza uno o más archivos de audio individualmente sin necesidad de re-subir el set completo."""
	get_or_create_job(proceso1_job_id)

	VALID_FIELDS = ['intro', 'parte1', 'parte2', 'parte3', 'parte4', 'cierre']
	from .core.audio_processor import get_audio_duration

	job_dir = get_job_dir(proceso1_job_id)
	input_dir = job_dir / 'input'
	input_dir.mkdir(parents=True, exist_ok=True)

	allowed_ext = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}

	# Cargar estado existente
	state = get_or_create_subprocess_state(proceso1_job_id, 'audio_input')
	existing_files: dict = (state.input_payload or {}).get('files') or {}
	existing_durations: dict = (state.output_payload or {}).get('durations') or {}

	if not existing_files:
		return jsonify({'error': 'No hay audios previos. Usa el endpoint /upload primero.'}), 400

	saved_paths = dict(existing_files)
	durations = dict(existing_durations)

	uploaded_any = False
	for field in VALID_FIELDS:
		if field in request.files:
			f = request.files[field]
			original_name = (f.filename or '').strip()
			ext = Path(original_name).suffix.lower() if original_name else ''
			if ext not in allowed_ext:
				ext = '.wav'
			out_path = input_dir / f'{field}{ext}'
			f.save(out_path)
			saved_paths[field] = str(out_path)
			durations[field] = float(get_audio_duration(str(out_path)) or 0)
			uploaded_any = True

	if not uploaded_any:
		return jsonify({'error': 'No se envió ningún archivo para reemplazar'}), 400

	# Preservar speed confirmada si ya fue guardada
	existing_input = dict(state.input_payload or {})
	payload = {
		'status': 'completed',
		'input': {
			**existing_input,
			'files': saved_paths,
		},
		'output': {
			'durations': durations,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/speed/run', methods=['POST'])
def run_speed(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	speed = float(body.get('speed') or 1.05)

	from .core.audio_processor import check_ffmpeg, speed_up_audio

	if not check_ffmpeg():
		return jsonify({'error': 'ffmpeg no está disponible. Instala ffmpeg o imageio-ffmpeg.'}), 400

	audio_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='audio_input').first()
	if not audio_state or not (audio_state.input_payload or {}).get('files'):
		return jsonify({'error': 'Primero sube los 5 MP3 en Audio Input'}), 400

	files: dict = (audio_state.input_payload or {}).get('files') or {}
	job_dir = get_job_dir(proceso1_job_id)
	work_dir = job_dir / 'work'
	work_dir.mkdir(parents=True, exist_ok=True)

	results: dict[str, dict] = {}
	for key, in_path in files.items():
		out_path = work_dir / f'{key}_speed.mp3'
		results[key] = speed_up_audio(str(in_path), str(out_path), speed=speed)

	state = get_or_create_subprocess_state(proceso1_job_id, 'speed')
	payload = {
		'status': 'completed',
		'input': {
			'speed': speed,
			'inputFiles': files,
		},
		'output': {
			'speedFiles': {k: v['output'] for k, v in results.items()},
			'details': results,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/concat/run', methods=['POST'])
def run_concat(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	transition_ms = int(body.get('transitionMs') or 2500)

	from .core.audio_processor import check_ffmpeg, concatenate_with_markers

	if not check_ffmpeg():
		return jsonify({'error': 'ffmpeg no está disponible. Instala ffmpeg o imageio-ffmpeg.'}), 400

	speed_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='speed').first()
	audio_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='audio_input').first()

	if not audio_state or not (audio_state.input_payload or {}).get('files'):
		return jsonify({'error': 'Primero completa Audio Input (sube los 5 audios)'}), 400

	# Velocidad: leer de audio_input.input.speed (confirmada en la Auditoría), default 1.05
	confirmed_speed = float((audio_state.input_payload or {}).get('speed') or 1.05)

	raw_files: dict = (audio_state.input_payload or {}).get('files') or {}
	ordered_keys = ['intro', 'parte1', 'parte2', 'parte3', 'parte4', 'cierre']

	# Si ya existe un speed subprocess con esa misma velocidad, re-usar los archivos ya procesados
	speed_already_applied = (
		speed_state
		and (speed_state.output_payload or {}).get('speedFiles')
		and float((speed_state.input_payload or {}).get('speed') or 0) == confirmed_speed
	)

	if speed_already_applied:
		files = dict((speed_state.output_payload or {}).get('speedFiles') or {})
	else:
		# Aplicar velocidad en el momento (in-place en work/) antes de concatenar
		from .core.audio_processor import check_ffmpeg, speed_up_audio
		if confirmed_speed != 1.0 and check_ffmpeg():
			job_dir_tmp = get_job_dir(proceso1_job_id)
			work_dir_tmp = job_dir_tmp / 'work'
			work_dir_tmp.mkdir(parents=True, exist_ok=True)
			speed_results: dict = {}
			for key, in_path in raw_files.items():
				out_path_s = work_dir_tmp / f'{key}_speed.mp3'
				speed_results[key] = speed_up_audio(str(in_path), str(out_path_s), speed=confirmed_speed)
			files = {k: v['output'] for k, v in speed_results.items()}
			# Guardar en subprocess speed para referencias futuras
			sp_speed = get_or_create_subprocess_state(proceso1_job_id, 'speed')
			_save_state(sp_speed, {
				'status': 'completed',
				'input': {'speed': confirmed_speed, 'inputFiles': raw_files},
				'output': {'speedFiles': files, 'details': speed_results},
			})
		else:
			files = dict(raw_files)

	audio_paths = [files[k] for k in ordered_keys if k in files]
	if len(audio_paths) != 6:
		return jsonify({'error': 'Faltan partes de audio para concatenar (esperadas: intro, parte1, parte2, parte3, parte4, cierre)'}), 400

	job_dir = get_job_dir(proceso1_job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	final_path = output_dir / 'final.mp3'

	labels = ordered_keys
	result = concatenate_with_markers(audio_paths, labels, str(final_path), transition_ms=transition_ms)

	state = get_or_create_subprocess_state(proceso1_job_id, 'concat')
	payload = {
		'status': 'completed',
		'input': {
			'transitionMs': transition_ms,
			'audioFiles': files,
		},
		'output': {
			'finalMp3': result['output'],
			'markersPath': result['markers_path'],
			'markers': result['markers'],
			'totalDuration': result['total_duration'],
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/srt/run', methods=['POST'])
def run_srt(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	language = str(body.get('language') or 'en')
	existing_srt_text = body.get('srtText')

	from .core.srt_generator import generate_srt_whisper, parse_srt_file

	concat_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='concat').first()
	if not concat_state or not (concat_state.output_payload or {}).get('finalMp3'):
		return jsonify({'error': 'Primero completa Concat para generar final.mp3'}), 400

	final_mp3 = str((concat_state.output_payload or {}).get('finalMp3'))
	job_dir = get_job_dir(proceso1_job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	srt_path = output_dir / 'final.srt'

	if isinstance(existing_srt_text, str) and existing_srt_text.strip():
		srt_path.write_text(existing_srt_text, encoding='utf-8')
		segments = parse_srt_file(str(srt_path))
		output = {
			'srtPath': str(srt_path),
			'segments': segments,
			'numSegments': len(segments),
			'source': 'manual',
		}
	else:
		result = generate_srt_whisper(final_mp3, str(srt_path), language=language)
		output = {
			'srtPath': result['srt_path'],
			'segmentsJsonPath': result['json_path'],
			'numSegments': result['num_segments'],
			'totalDuration': result['total_duration'],
			# Do NOT return all segments (could be huge). Keep a preview.
			'segmentsPreview': (result['segments'] or [])[:5],
			'source': 'whisper',
		}

	state = get_or_create_subprocess_state(proceso1_job_id, 'srt')
	payload = {
		'status': 'completed',
		'input': {
			'language': language,
			'usedManualSrt': bool(isinstance(existing_srt_text, str) and existing_srt_text.strip()),
		},
		'output': output,
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/subprocesses/scenes/run', methods=['POST'])
def run_scenes(proceso1_job_id: int):
	get_or_create_job(proceso1_job_id)
	body = request.get_json(silent=True) or {}
	target = float(body.get('sceneDurationTarget') or 18.0)

	from .core.scene_segmenter import export_scenes_json, get_scene_stats, segment_into_scenes
	from .core.srt_generator import parse_srt_file

	concat_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='concat').first()
	srt_state = Proceso2SubprocessState.query.filter_by(proceso1_job_id=proceso1_job_id, subprocess_key='srt').first()

	if not concat_state or not (concat_state.output_payload or {}).get('markersPath'):
		return jsonify({'error': 'Primero completa Concat (markers.json)'}), 400
	if not srt_state or not (srt_state.output_payload or {}).get('srtPath'):
		return jsonify({'error': 'Primero completa SRT (final.srt)'}), 400

	markers_path = Path(str((concat_state.output_payload or {}).get('markersPath')))
	srt_path = Path(str((srt_state.output_payload or {}).get('srtPath')))
	if not markers_path.exists():
		return jsonify({'error': f'No se encontró markers.json en: {markers_path}'}), 400
	if not srt_path.exists():
		return jsonify({'error': f'No se encontró SRT en: {srt_path}'}), 400

	markers = json.loads(markers_path.read_text(encoding='utf-8'))
	srt_segments = parse_srt_file(str(srt_path))

	scenes = segment_into_scenes(markers=markers, srt_segments=srt_segments, scene_duration_target=target)

	job_dir = get_job_dir(proceso1_job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	scenes_path = output_dir / 'scenes.json'
	export_scenes_json(scenes, str(scenes_path))
	stats = get_scene_stats(scenes)

	state = get_or_create_subprocess_state(proceso1_job_id, 'scenes')
	payload = {
		'status': 'completed',
		'input': {
			'sceneDurationTarget': target,
		},
		'output': {
			'scenesPath': str(scenes_path),
			'stats': stats,
			'scenes': scenes,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_bp.route('/jobs/<int:proceso1_job_id>/output/<path:filename>', methods=['GET'])
def download_output_file(proceso1_job_id: int, filename: str):
	"""Sirve un archivo de la carpeta output/ del job (final.mp3, final.srt, scenes.json, markers.json)."""
	from flask import send_file, abort
	import re

	# Seguridad: sólo nombres de archivo simples, sin rutas relativas (../../) ni separadores
	safe_name = re.sub(r'[^A-Za-z0-9_.\-]', '', Path(filename).name)
	if not safe_name:
		abort(400, 'Nombre de archivo inválido')

	file_path = get_job_dir(proceso1_job_id) / 'output' / safe_name
	if not file_path.exists():
		abort(404, f'Archivo no encontrado: {safe_name}')

	return send_file(str(file_path), as_attachment=True, download_name=safe_name)


__all__ = [
	'proceso2_bp',
]
