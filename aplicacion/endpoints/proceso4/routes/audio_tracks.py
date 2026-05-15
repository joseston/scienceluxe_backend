from __future__ import annotations

import logging
import uuid
from pathlib import Path

from flask import jsonify, request, send_file

from aplicacion import db
from aplicacion.models.proceso4 import (
	Proceso4AudioTrack,
	Proceso4MusicTemplate,
	Proceso4MusicTemplateItem,
	Proceso4ReverbConfig,
	Proceso4SectionTrack,
	Proceso4SubprocessState,
)

from .. import proceso4_bp
from ..constants import PISTAS_DIR, SECTIONS_ORDER
from ..helpers import get_or_create_job, get_job_dir, get_or_create_subprocess_state, _save_state

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audio Tracks (music, sfx)
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/audio-tracks', methods=['POST'])
def upload_audio_track(pid: int):
	"""Upload an extra audio track (music or sfx)."""
	get_or_create_job(pid)

	if 'file' not in request.files:
		return jsonify({'error': 'No file in request.'}), 400

	f = request.files['file']
	if not f.filename:
		return jsonify({'error': 'Empty filename.'}), 400

	track_type = request.form.get('trackType', 'music')
	start_time = float(request.form.get('startTime', 0))
	volume = float(request.form.get('volume', 0.3))

	ext = (f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'mp3').lower()
	audio_dir = get_job_dir(pid) / 'audio_tracks'
	audio_dir.mkdir(parents=True, exist_ok=True)
	safe_name = f"{track_type}_{uuid.uuid4().hex[:8]}.{ext}"
	out_path = audio_dir / safe_name
	f.save(str(out_path))

	record = Proceso4AudioTrack(
		proceso1_job_id=pid,
		track_type=track_type,
		original_filename=f.filename,
		file_path=str(out_path),
		start_time=start_time,
		volume=volume,
	)
	db.session.add(record)
	db.session.commit()
	return jsonify(record.to_dict()), 201


@proceso4_bp.route('/jobs/<int:pid>/audio-tracks', methods=['GET'])
def list_audio_tracks(pid: int):
	get_or_create_job(pid)
	tracks = Proceso4AudioTrack.query.filter_by(proceso1_job_id=pid).all()
	db.session.commit()
	return jsonify([t.to_dict() for t in tracks])


@proceso4_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>', methods=['PUT'])
def update_audio_track(pid: int, track_id: int):
	get_or_create_job(pid)
	record = Proceso4AudioTrack.query.get_or_404(track_id)
	if record.proceso1_job_id != pid:
		return jsonify({'error': 'Not found'}), 404

	body = request.get_json(force=True) or {}
	if 'startTime' in body:
		record.start_time = float(body['startTime'])
	if 'volume' in body:
		record.volume = float(body['volume'])
	if 'trackType' in body:
		record.track_type = str(body['trackType'])

	db.session.commit()
	return jsonify(record.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>', methods=['DELETE'])
def delete_audio_track(pid: int, track_id: int):
	get_or_create_job(pid)
	record = Proceso4AudioTrack.query.get_or_404(track_id)
	if record.proceso1_job_id != pid:
		return jsonify({'error': 'Not found'}), 404

	try:
		fp = Path(record.file_path)
		if fp.exists():
			fp.unlink()
	except Exception as e:
		logger.warning(f"Could not delete audio track file: {e}")

	db.session.delete(record)
	db.session.commit()
	return jsonify({'ok': True})


@proceso4_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>/file', methods=['GET'])
def serve_audio_track_file(pid: int, track_id: int):
	"""Serve an extra audio track file for preview playback."""
	get_or_create_job(pid)
	record = Proceso4AudioTrack.query.get_or_404(track_id)
	if record.proceso1_job_id != pid:
		return jsonify({'error': 'Not found'}), 404
	fp = Path(record.file_path)
	if not fp.exists():
		return jsonify({'error': 'Audio track file not found on disk'}), 404
	return send_file(str(fp), mimetype='audio/mpeg', conditional=True)


# ---------------------------------------------------------------------------
# Section Pistas (per-section music tracks)
# ---------------------------------------------------------------------------

@proceso4_bp.route('/available-pistas', methods=['GET'])
def list_available_pistas():
	"""List MP3 pistas available from the shared pistas directory."""
	if not PISTAS_DIR.exists():
		return jsonify([])
	pistas = []
	for f in sorted(PISTAS_DIR.iterdir()):
		if f.suffix.lower() in ('.mp3', '.wav', '.ogg', '.flac'):
			pistas.append({
				'filename': f.name,
				'path': str(f),
			})
	return jsonify(pistas)


@proceso4_bp.route('/pistas-file/<path:filename>', methods=['GET'])
def serve_pista_file(filename: str):
	"""Serve a pista MP3 for preview playback."""
	safe_name = Path(filename).name  # prevent path traversal
	fp = PISTAS_DIR / safe_name
	if not fp.exists():
		return jsonify({'error': 'Pista no encontrada'}), 404
	return send_file(str(fp), mimetype='audio/mpeg', conditional=True)


@proceso4_bp.route('/jobs/<int:pid>/section-tracks', methods=['GET'])
def list_section_tracks(pid: int):
	"""List all section pistas assigned to this project."""
	get_or_create_job(pid)
	tracks = Proceso4SectionTrack.query.filter_by(proceso1_job_id=pid).all()
	db.session.commit()
	return jsonify([t.to_dict() for t in tracks])


@proceso4_bp.route('/jobs/<int:pid>/section-tracks/<string:section>', methods=['PUT'])
def upsert_section_track(pid: int, section: str):
	"""Assign or update a pista for a specific section."""
	get_or_create_job(pid)
	body = request.get_json(force=True) or {}
	pista_filename = body.get('pistaFilename', '').strip()
	if not pista_filename:
		return jsonify({'error': 'pistaFilename es requerido'}), 400

	pista_path = str(PISTAS_DIR / pista_filename)
	if not Path(pista_path).exists():
		return jsonify({'error': f'Pista no encontrada: {pista_filename}'}), 404

	record = Proceso4SectionTrack.query.filter_by(
		proceso1_job_id=pid, section=section
	).first()

	if record:
		record.pista_filename = pista_filename
		record.pista_path = pista_path
		if 'volume' in body:
			record.volume = float(body['volume'])
		if 'fadeIn' in body:
			record.fade_in = float(body['fadeIn'])
		if 'fadeOut' in body:
			record.fade_out = float(body['fadeOut'])
		if 'startOffset' in body:
			record.start_offset = max(0.0, float(body['startOffset']))
	else:
		record = Proceso4SectionTrack(
			proceso1_job_id=pid,
			section=section,
			pista_filename=pista_filename,
			pista_path=pista_path,
			volume=float(body.get('volume', 0.15)),
			fade_in=float(body.get('fadeIn', 1.0)),
			fade_out=float(body.get('fadeOut', 2.0)),
			start_offset=max(0.0, float(body.get('startOffset', 0.0))),
		)
		db.session.add(record)

	db.session.commit()
	return jsonify(record.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/section-tracks/<string:section>', methods=['DELETE'])
def delete_section_track(pid: int, section: str):
	"""Remove the pista assignment for a section."""
	get_or_create_job(pid)
	record = Proceso4SectionTrack.query.filter_by(
		proceso1_job_id=pid, section=section
	).first()
	if not record:
		return jsonify({'error': 'No hay pista asignada a esta sección'}), 404
	db.session.delete(record)
	db.session.commit()
	return jsonify({'ok': True})


@proceso4_bp.route('/jobs/<int:pid>/auto-assign-pistas', methods=['POST'])
def auto_assign_pistas(pid: int):
	"""Auto-assign available pistas to sections round-robin."""
	get_or_create_job(pid)

	# Determine sections from the imported timeline
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='import_timeline'
	).first()
	if not import_state or import_state.status != 'completed':
		return jsonify({'error': 'Timeline no importado todavía.'}), 400

	tl = (import_state.output_payload or {}).get('timeline', {})
	scenes = tl.get('scenes', [])
	# Extract unique sections in order of appearance
	seen = set()
	sections_ordered = []
	for s in scenes:
		sec = s.get('section', '')
		if sec and sec not in seen:
			seen.add(sec)
			sections_ordered.append(sec)

	if not sections_ordered:
		return jsonify({'error': 'No se encontraron secciones en el timeline'}), 400

	# Get available pistas
	if not PISTAS_DIR.exists():
		return jsonify({'error': f'Directorio de pistas no encontrado: {PISTAS_DIR}'}), 400
	pistas = sorted([f for f in PISTAS_DIR.iterdir() if f.suffix.lower() in ('.mp3', '.wav', '.ogg', '.flac')])
	if not pistas:
		return jsonify({'error': 'No hay pistas disponibles en el directorio'}), 400

	# Clear existing section tracks for this job
	Proceso4SectionTrack.query.filter_by(proceso1_job_id=pid).delete()

	# Assign round-robin
	assigned = []
	for i, section in enumerate(sections_ordered):
		pista = pistas[i % len(pistas)]
		track = Proceso4SectionTrack(
			proceso1_job_id=pid,
			section=section,
			pista_filename=pista.name,
			pista_path=str(pista),
			volume=0.15,
			fade_in=1.0,
			fade_out=2.0,
		)
		db.session.add(track)
		assigned.append(track)

	db.session.commit()
	return jsonify({
		'assigned': [t.to_dict() for t in assigned],
		'sections': sections_ordered,
	})


def _section_sort_key(section: str) -> tuple[int, str]:
	try:
		return (SECTIONS_ORDER.index(section), section)
	except ValueError:
		return (len(SECTIONS_ORDER), section)


@proceso4_bp.route('/music-templates', methods=['GET'])
def list_music_templates():
	"""List global reusable music templates."""
	templates = Proceso4MusicTemplate.query.order_by(Proceso4MusicTemplate.name.asc()).all()
	return jsonify([template.to_dict() for template in templates])


@proceso4_bp.route('/music-templates', methods=['POST'])
def save_music_template():
	"""Create or update a reusable music template from section tracks."""
	body = request.get_json(force=True) or {}
	name = str(body.get('name', '')).strip()
	raw_items = body.get('items') or []
	if not name:
		return jsonify({'error': 'name es requerido'}), 400
	if not isinstance(raw_items, list) or not raw_items:
		return jsonify({'error': 'items debe ser una lista con al menos una seccion'}), 400

	normalized_items: list[dict[str, object]] = []
	seen_sections: set[str] = set()
	missing_files: list[str] = []
	for raw in raw_items:
		section = str((raw or {}).get('section', '')).strip()
		pista_filename = str((raw or {}).get('pistaFilename', '')).strip()
		if not section or not pista_filename:
			return jsonify({'error': 'Cada item necesita section y pistaFilename'}), 400
		if section in seen_sections:
			return jsonify({'error': f'Seccion duplicada en plantilla: {section}'}), 400
		seen_sections.add(section)
		if not (PISTAS_DIR / pista_filename).exists():
			missing_files.append(pista_filename)
		normalized_items.append({
			'section': section,
			'pista_filename': pista_filename,
			'volume': float((raw or {}).get('volume', 0.15)),
			'fade_in': float((raw or {}).get('fadeIn', 1.0)),
			'fade_out': float((raw or {}).get('fadeOut', 2.0)),
			'start_offset': max(0.0, float((raw or {}).get('startOffset', 0.0))),
		})

	if missing_files:
		return jsonify({'error': f'Pistas no encontradas: {", ".join(sorted(set(missing_files)))}'}), 400

	normalized_items.sort(key=lambda item: _section_sort_key(str(item['section'])))
	template = Proceso4MusicTemplate.query.filter_by(name=name).first()
	if not template:
		template = Proceso4MusicTemplate(name=name)
		db.session.add(template)
		db.session.flush()
	else:
		Proceso4MusicTemplateItem.query.filter_by(template_id=template.id).delete()

	for item in normalized_items:
		db.session.add(Proceso4MusicTemplateItem(
			template_id=template.id,
			section=str(item['section']),
			pista_filename=str(item['pista_filename']),
			volume=float(item['volume']),
			fade_in=float(item['fade_in']),
			fade_out=float(item['fade_out']),
			start_offset=float(item['start_offset']),
		))

	db.session.commit()
	refreshed = Proceso4MusicTemplate.query.get(template.id)
	return jsonify(refreshed.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/music-templates/<int:template_id>/apply', methods=['POST'])
def apply_music_template(pid: int, template_id: int):
	"""Apply a saved music template to the current video job."""
	get_or_create_job(pid)
	template = Proceso4MusicTemplate.query.get_or_404(template_id)
	items = sorted(template.items or [], key=lambda item: _section_sort_key(item.section))
	if not items:
		return jsonify({'error': 'La plantilla no tiene secciones configuradas'}), 400

	missing_files = [item.pista_filename for item in items if not (PISTAS_DIR / item.pista_filename).exists()]
	if missing_files:
		return jsonify({'error': f'Faltan pistas para aplicar plantilla: {", ".join(sorted(set(missing_files)))}'}), 400

	Proceso4SectionTrack.query.filter_by(proceso1_job_id=pid).delete()

	assigned: list[Proceso4SectionTrack] = []
	for item in items:
		track = Proceso4SectionTrack(
			proceso1_job_id=pid,
			section=item.section,
			pista_filename=item.pista_filename,
			pista_path=str(PISTAS_DIR / item.pista_filename),
			volume=item.volume,
			fade_in=item.fade_in,
			fade_out=item.fade_out,
			start_offset=item.start_offset,
		)
		db.session.add(track)
		assigned.append(track)

	db.session.commit()
	return jsonify({
		'ok': True,
		'assigned': [track.to_dict() for track in assigned],
		'template': template.to_dict(),
	})


# ---------------------------------------------------------------------------
# Reverb Config
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/reverb-config', methods=['GET'])
def get_reverb_config(pid: int):
	"""Get reverb configuration for this project."""
	get_or_create_job(pid)
	config = Proceso4ReverbConfig.query.get(pid)
	if not config:
		# Return defaults
		return jsonify({
			'proceso1JobId': pid,
			'enabled': True,
			'inGain': 0.8,
			'outGain': 0.88,
			'delayMs': 60.0,
			'decay': 0.4,
		})
	db.session.commit()
	return jsonify(config.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/reverb-config', methods=['PUT'])
def update_reverb_config(pid: int):
	"""Update reverb configuration for this project."""
	get_or_create_job(pid)
	body = request.get_json(force=True) or {}

	config = Proceso4ReverbConfig.query.get(pid)
	if not config:
		config = Proceso4ReverbConfig(proceso1_job_id=pid)
		db.session.add(config)

	if 'enabled' in body:
		config.enabled = bool(body['enabled'])
	if 'inGain' in body:
		config.in_gain = float(body['inGain'])
	if 'outGain' in body:
		config.out_gain = float(body['outGain'])
	if 'delayMs' in body:
		config.delay_ms = float(body['delayMs'])
	if 'decay' in body:
		config.decay = float(body['decay'])

	db.session.commit()
	return jsonify(config.to_dict())
