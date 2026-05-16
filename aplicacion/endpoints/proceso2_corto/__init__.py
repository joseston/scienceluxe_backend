from __future__ import annotations

from flask import Blueprint, jsonify, request
from pathlib import Path
import json

from aplicacion import db
from aplicacion.models.proceso1_corto import Proceso1CortoJob
from aplicacion.models.proceso2_corto import Proceso2CortoJob, Proceso2CortoSubprocessState
from config import STORAGE_ROOT as STORAGE_ROOT_CONFIG


proceso2_corto_bp = Blueprint('proceso2_corto', __name__)


# Raíz de almacenamiento persistente en disco
STORAGE_ROOT = Path(STORAGE_ROOT_CONFIG)

# Duración máxima permitida para un audio corto: 2 minutos
MAX_AUDIO_DURATION_SECONDS = 120


def _get_video_id(proceso1_corto_job_id: int) -> str:
	"""Devuelve el video_id del Proceso1CortoJob, o el ID numérico como fallback."""
	try:
		import re
		job = Proceso1CortoJob.query.get(proceso1_corto_job_id)
		if job and job.video_id:
			return re.sub(r'[^A-Za-z0-9_\-]', '_', job.video_id)[:60]
		return str(proceso1_corto_job_id)
	except Exception:
		return str(proceso1_corto_job_id)


def get_job_dir(proceso1_corto_job_id: int) -> Path:
	video_id = _get_video_id(proceso1_corto_job_id)
	return STORAGE_ROOT / f'corto_{proceso1_corto_job_id}_{video_id}'


def get_or_create_job(proceso1_corto_job_id: int) -> Proceso2CortoJob:
	Proceso1CortoJob.query.get_or_404(proceso1_corto_job_id)
	job = Proceso2CortoJob.query.get(proceso1_corto_job_id)
	if job is None:
		job = Proceso2CortoJob(proceso1_corto_job_id=proceso1_corto_job_id)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(proceso1_corto_job_id: int, subprocess_key: str) -> Proceso2CortoSubprocessState:
	state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=proceso1_corto_job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso2CortoSubprocessState(proceso1_corto_job_id=proceso1_corto_job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state


def _save_state(state: Proceso2CortoSubprocessState, payload: dict) -> Proceso2CortoSubprocessState:
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
# Job lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@proceso2_corto_bp.route('/jobs/<int:job_id>/init', methods=['POST'])
def init_job(job_id: int):
	job = get_or_create_job(job_id)
	job_dir = get_job_dir(job_id)
	(job_dir / 'input').mkdir(parents=True, exist_ok=True)
	(job_dir / 'work').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id: int):
	job = get_or_create_job(job_id)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/<string:subprocess_key>', methods=['GET'])
def get_subprocess_state(job_id: int, subprocess_key: str):
	get_or_create_job(job_id)
	state = get_or_create_subprocess_state(job_id, subprocess_key)
	db.session.commit()
	return jsonify(state.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/<string:subprocess_key>', methods=['PUT'])
def save_subprocess_state(job_id: int, subprocess_key: str):
	get_or_create_job(job_id)
	state = get_or_create_subprocess_state(job_id, subprocess_key)
	payload = request.get_json(silent=True) or {}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_corto_bp.route('/whisper/status', methods=['GET'])
def whisper_status():
	from aplicacion.endpoints.proceso2.core.srt_generator import check_whisper_status
	return jsonify(check_whisper_status())


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline endpoints
# Subprocess keys: audio_input, speed, srt, scenes
# (NO concat — el audio corto es un solo archivo)
# ─────────────────────────────────────────────────────────────────────────────


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/audio_input/upload', methods=['POST'])
def upload_audio(job_id: int):
	"""Sube un único archivo de audio para video corto (máx 2 min)."""
	get_or_create_job(job_id)

	if 'audio' not in request.files:
		return jsonify({'error': 'Se requiere un archivo con el campo "audio"'}), 400

	from aplicacion.endpoints.proceso2.core.audio_processor import get_audio_duration

	f = request.files['audio']
	original_name = (f.filename or '').strip()
	ext = Path(original_name).suffix.lower() if original_name else ''

	allowed_ext = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
	if ext not in allowed_ext:
		ext = '.wav'

	job_dir = get_job_dir(job_id)
	input_dir = job_dir / 'input'
	input_dir.mkdir(parents=True, exist_ok=True)

	out_path = input_dir / f'audio{ext}'
	f.save(out_path)

	duration = float(get_audio_duration(str(out_path)) or 0)

	# Validar duración máxima: 2 minutos
	if duration > MAX_AUDIO_DURATION_SECONDS:
		# Eliminar archivo subido
		try:
			out_path.unlink()
		except Exception:
			pass
		return jsonify({
			'error': f'El audio excede la duración máxima de {MAX_AUDIO_DURATION_SECONDS}s ({duration:.1f}s). Máximo 2 minutos.',
		}), 400

	state = get_or_create_subprocess_state(job_id, 'audio_input')
	payload = {
		'status': 'completed',
		'input': {
			'file': str(out_path),
			'originalName': original_name,
		},
		'output': {
			'duration': duration,
			'filePath': str(out_path),
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/audio_input/replace', methods=['PATCH'])
def replace_audio(job_id: int):
	"""Reemplaza el archivo de audio sin re-crear el job."""
	get_or_create_job(job_id)

	if 'audio' not in request.files:
		return jsonify({'error': 'Se requiere un archivo con el campo "audio"'}), 400

	state = get_or_create_subprocess_state(job_id, 'audio_input')
	existing_file = (state.input_payload or {}).get('file')
	if not existing_file:
		return jsonify({'error': 'No hay audio previo. Usa el endpoint /upload primero.'}), 400

	from aplicacion.endpoints.proceso2.core.audio_processor import get_audio_duration

	f = request.files['audio']
	original_name = (f.filename or '').strip()
	ext = Path(original_name).suffix.lower() if original_name else ''

	allowed_ext = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
	if ext not in allowed_ext:
		ext = '.wav'

	job_dir = get_job_dir(job_id)
	input_dir = job_dir / 'input'
	input_dir.mkdir(parents=True, exist_ok=True)

	out_path = input_dir / f'audio{ext}'
	f.save(out_path)

	duration = float(get_audio_duration(str(out_path)) or 0)

	if duration > MAX_AUDIO_DURATION_SECONDS:
		try:
			out_path.unlink()
		except Exception:
			pass
		return jsonify({
			'error': f'El audio excede la duración máxima de {MAX_AUDIO_DURATION_SECONDS}s ({duration:.1f}s). Máximo 2 minutos.',
		}), 400

	payload = {
		'status': 'completed',
		'input': {
			'file': str(out_path),
			'originalName': original_name,
		},
		'output': {
			'duration': duration,
			'filePath': str(out_path),
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/speed/run', methods=['POST'])
def run_speed(job_id: int):
	"""Aplica velocidad (atempo) al audio único."""
	get_or_create_job(job_id)
	body = request.get_json(silent=True) or {}
	speed = float(body.get('speed') or 1.05)

	from aplicacion.endpoints.proceso2.core.audio_processor import check_ffmpeg, speed_up_audio

	if not check_ffmpeg():
		return jsonify({'error': 'ffmpeg no está disponible. Instala ffmpeg o imageio-ffmpeg.'}), 400

	audio_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id, subprocess_key='audio_input',
	).first()
	if not audio_state or not (audio_state.input_payload or {}).get('file'):
		return jsonify({'error': 'Primero sube el audio en Audio Input'}), 400

	input_file = str((audio_state.input_payload or {}).get('file'))

	job_dir = get_job_dir(job_id)
	work_dir = job_dir / 'work'
	work_dir.mkdir(parents=True, exist_ok=True)

	out_path = work_dir / 'audio_speed.mp3'
	result = speed_up_audio(input_file, str(out_path), speed=speed)

	state = get_or_create_subprocess_state(job_id, 'speed')
	payload = {
		'status': 'completed',
		'input': {
			'speed': speed,
			'inputFile': input_file,
		},
		'output': {
			'speedFile': result['output'],
			'details': result,
		},
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/srt/run', methods=['POST'])
def run_srt(job_id: int):
	"""Genera SRT con Whisper sobre el audio (speed o raw)."""
	get_or_create_job(job_id)
	body = request.get_json(silent=True) or {}
	language = str(body.get('language') or 'en')
	existing_srt_text = body.get('srtText')

	from aplicacion.endpoints.proceso2.core.srt_generator import generate_srt_whisper, parse_srt_file

	# Determinar qué archivo de audio usar: speed si existe, si no el original
	speed_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id, subprocess_key='speed',
	).first()
	audio_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id, subprocess_key='audio_input',
	).first()

	if not audio_state or not (audio_state.input_payload or {}).get('file'):
		return jsonify({'error': 'Primero sube el audio en Audio Input'}), 400

	# Usar audio con speed si disponible, si no el original
	if speed_state and (speed_state.output_payload or {}).get('speedFile'):
		audio_file = str((speed_state.output_payload or {}).get('speedFile'))
	else:
		audio_file = str((audio_state.input_payload or {}).get('file'))

	job_dir = get_job_dir(job_id)
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
		result = generate_srt_whisper(audio_file, str(srt_path), language=language)
		output = {
			'srtPath': result['srt_path'],
			'segmentsJsonPath': result['json_path'],
			'numSegments': result['num_segments'],
			'totalDuration': result['total_duration'],
			'segmentsPreview': (result['segments'] or [])[:5],
			'source': 'whisper',
		}

	state = get_or_create_subprocess_state(job_id, 'srt')
	payload = {
		'status': 'completed',
		'input': {
			'language': language,
			'usedManualSrt': bool(isinstance(existing_srt_text, str) and existing_srt_text.strip()),
			'audioFile': audio_file,
		},
		'output': output,
	}
	saved = _save_state(state, payload)
	return jsonify(saved.to_dict())


@proceso2_corto_bp.route('/jobs/<int:job_id>/subprocesses/scenes/run', methods=['POST'])
def run_scenes(job_id: int):
	"""Segmenta en escenas usando solo SRT (target ~5-6s para cortos)."""
	get_or_create_job(job_id)
	body = request.get_json(silent=True) or {}
	target = float(body.get('sceneDurationTarget') or 5.0)

	from .core.scene_segmenter_corto import export_scenes_json, get_scene_stats, segment_into_scenes_corto
	from aplicacion.endpoints.proceso2.core.srt_generator import parse_srt_file

	srt_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=job_id, subprocess_key='srt',
	).first()

	if not srt_state or not (srt_state.output_payload or {}).get('srtPath'):
		return jsonify({'error': 'Primero completa SRT (final.srt)'}), 400

	srt_path = Path(str((srt_state.output_payload or {}).get('srtPath')))
	if not srt_path.exists():
		return jsonify({'error': f'No se encontró SRT en: {srt_path}'}), 400

	srt_segments = parse_srt_file(str(srt_path))

	scenes = segment_into_scenes_corto(srt_segments=srt_segments, scene_duration_target=target)

	job_dir = get_job_dir(job_id)
	output_dir = job_dir / 'output'
	output_dir.mkdir(parents=True, exist_ok=True)
	scenes_path = output_dir / 'scenes.json'
	export_scenes_json(scenes, str(scenes_path))
	stats = get_scene_stats(scenes)

	state = get_or_create_subprocess_state(job_id, 'scenes')
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


@proceso2_corto_bp.route('/jobs/<int:job_id>/output/<path:filename>', methods=['GET'])
def download_output_file(job_id: int, filename: str):
	"""Sirve un archivo de la carpeta output/ del job."""
	from flask import send_file, abort
	import re

	safe_name = re.sub(r'[^A-Za-z0-9_.\-]', '', Path(filename).name)
	if not safe_name:
		abort(400, 'Nombre de archivo inválido')

	file_path = get_job_dir(job_id) / 'output' / safe_name
	if not file_path.exists():
		abort(404, f'Archivo no encontrado: {safe_name}')

	return send_file(str(file_path), as_attachment=True, download_name=safe_name)


__all__ = [
	'proceso2_corto_bp',
]
