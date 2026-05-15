from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, request, send_file

from aplicacion import db
from aplicacion.models.proceso4 import Proceso4GlobalAsset

from .. import proceso4_bp
from ..helpers import get_global_assets_dir

logger = logging.getLogger(__name__)

@proceso4_bp.route('/global-assets', methods=['GET'])
def list_global_assets():
	"""List all global Proceso 4 assets."""
	assets = Proceso4GlobalAsset.query.all()
	return jsonify([a.to_dict() for a in assets])


@proceso4_bp.route('/global-assets', methods=['POST'])
def upload_global_asset():
	"""Upload/replace a global asset (e.g. indice_image, indice_music)."""
	asset_key = (request.form.get('asset_key') or '').strip()
	if not asset_key:
		return jsonify({'error': 'Falta el campo asset_key'}), 400
	if 'file' not in request.files:
		return jsonify({'error': 'No se envió ningún archivo'}), 400

	allowed_keys = {'indice_image'}
	if asset_key not in allowed_keys:
		return jsonify({'error': f'asset_key inválido. Valores permitidos: {allowed_keys}'}), 400

	file = request.files['file']
	original_filename = file.filename or ''
	ext = Path(original_filename).suffix.lower() or ''

	assets_dir = get_global_assets_dir()
	dest_name = f'{asset_key}{ext}'
	dest_path = assets_dir / dest_name

	# Remove old file if key already exists with a different extension
	existing = Proceso4GlobalAsset.query.filter_by(asset_key=asset_key).first()
	if existing and Path(existing.file_path).exists():
		try:
			Path(existing.file_path).unlink(missing_ok=True)
		except Exception:
			pass

	file.save(str(dest_path))

	if existing:
		existing.original_filename = original_filename
		existing.file_path = str(dest_path)
	else:
		existing = Proceso4GlobalAsset(
			asset_key=asset_key,
			original_filename=original_filename,
			file_path=str(dest_path),
		)
		db.session.add(existing)

	db.session.commit()
	return jsonify(existing.to_dict()), 201


@proceso4_bp.route('/global-assets/<int:asset_id>', methods=['DELETE'])
def delete_global_asset(asset_id: int):
	"""Delete a global asset record and file."""
	asset = Proceso4GlobalAsset.query.get_or_404(asset_id)
	try:
		Path(asset.file_path).unlink(missing_ok=True)
	except Exception:
		pass
	db.session.delete(asset)
	db.session.commit()
	return jsonify({'deleted': True})


@proceso4_bp.route('/global-assets/file/<string:asset_key>', methods=['GET'])
def serve_global_asset_file(asset_key: str):
	"""Serve the file for a global asset (e.g. for image preview)."""
	asset = Proceso4GlobalAsset.query.filter_by(asset_key=asset_key).first_or_404()
	p = Path(asset.file_path)
	if not p.exists():
		return jsonify({'error': 'Archivo no encontrado en disco'}), 404
	return send_file(str(p), as_attachment=False)

