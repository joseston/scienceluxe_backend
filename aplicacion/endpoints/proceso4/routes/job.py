from __future__ import annotations

import logging

from flask import jsonify, request

from aplicacion import db
from aplicacion.models.proceso4 import Proceso4SubprocessState

from .. import proceso4_bp
from ..helpers import (
	_get_indice_data,
	_get_timeline_from_proceso3,
	_save_state,
	get_job_dir,
	get_or_create_job,
	get_or_create_subprocess_state,
	normalize_render_state_output_path,
)

logger = logging.getLogger(__name__)


def _enrich_auto_indice_entry(pid: int, entry: dict) -> dict:
	"""Backfill indice data for legacy states without overriding saved manual edits."""
	if entry.get('subprocessKey') != 'auto_indice':
		return entry
	output = dict(entry.get('output') or {})
	if output.get('subtemas'):
		entry['output'] = output
		return entry
	try:
		indice_data = _get_indice_data(pid)
		if indice_data['subtemas']:
			output['subtemas'] = indice_data['subtemas']
			output.setdefault('indice_text', indice_data.get('indice_text') or '')
			entry['output'] = output
	except Exception as exc:
		logger.warning(f'[P4] Could not enrich auto_indice subtemas for pid={pid}: {exc}')
	return entry


# ---------------------------------------------------------------------------
# CRUD — Job
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/init', methods=['POST'])
def init_job(pid: int):
	"""Initialize Proceso 4 job. Creates dirs, imports timeline from P3."""
	job = get_or_create_job(pid)
	job_dir = get_job_dir(pid)
	(job_dir / 'media').mkdir(parents=True, exist_ok=True)
	(job_dir / 'audio_tracks').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()

	# Auto-import timeline from Proceso 3 if not already done
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	if import_state.status != 'completed':
		tl = _get_timeline_from_proceso3(pid)
		if tl:
			_save_state(import_state, {
				'status': 'completed',
				'output': {'timeline': tl},
			})
		else:
			_save_state(import_state, {'status': 'draft'})
	db.session.commit()

	return jsonify(job.to_dict())


@proceso4_bp.route('/jobs/<int:pid>', methods=['GET'])
def get_job(pid: int):
	job = get_or_create_job(pid)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso4_bp.route('/jobs/<int:pid>/subprocesses', methods=['GET'])
def list_subprocess_states(pid: int):
	get_or_create_job(pid)
	get_job_dir(pid)
	states = (
		Proceso4SubprocessState.query
		.filter_by(proceso1_job_id=pid)
		.order_by(Proceso4SubprocessState.id)
		.all()
	)
	changed = False
	for state in states:
		if normalize_render_state_output_path(state):
			changed = True
	if changed:
		db.session.commit()
	db.session.commit()
	result = [_enrich_auto_indice_entry(pid, s.to_dict()) for s in states]
	return jsonify(result)


@proceso4_bp.route('/jobs/<int:pid>/subprocesses/<string:key>', methods=['GET'])
def get_subprocess_state(pid: int, key: str):
	get_or_create_job(pid)
	get_job_dir(pid)
	state = get_or_create_subprocess_state(pid, key)
	if normalize_render_state_output_path(state):
		db.session.commit()
	db.session.commit()
	return jsonify(_enrich_auto_indice_entry(pid, state.to_dict()))


@proceso4_bp.route('/jobs/<int:pid>/subprocesses/<string:key>', methods=['PUT'])
def update_subprocess_state(pid: int, key: str):
	get_or_create_job(pid)
	state = get_or_create_subprocess_state(pid, key)
	body = request.get_json(force=True) or {}
	saved = _save_state(state, body)
	return jsonify(saved.to_dict())
