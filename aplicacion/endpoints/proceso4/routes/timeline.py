from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, send_file

from aplicacion import db
from aplicacion.models.proceso4 import Proceso4SceneMedia, Proceso4SubprocessState

from .. import proceso4_bp
from ..helpers import (
	get_or_create_job,
	get_or_create_subprocess_state,
	_get_final_mp3_path,
	_get_timeline_from_proceso3,
	_effective_clip_duration,
	_build_section_title_metadata,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeline from P3
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/timeline', methods=['GET'])
def get_timeline(pid: int):
	"""Return the imported timeline (scenes from P3) + media assignment status."""
	get_or_create_job(pid)
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()

	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'Timeline no importado. Completa primero el Proceso 3 (Timeline).'}), 404

	scenes = tl.get('scenes', [])

	# Attach media info per scene
	all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
		Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
	).all()
	media_by_scene: dict[int, list[dict]] = {}
	for m in all_media:
		media_by_scene.setdefault(m.scene_num, []).append(m.to_dict())

	# Pre-compute effective durations (same logic as render loop) so the
	# frontend knows the REAL duration each scene must cover (including
	# inter-scene VAD gaps and section-boundary silences).
	effective_durations: list[float] = []
	for i, sc in enumerate(scenes):
		sc_start = float(sc.get('start', 0.0))
		sc_dur   = float(sc.get('duration', 5.0))
		if i + 1 < len(scenes):
			next_start = float(scenes[i + 1].get('start', 0.0))
			gap = round(next_start - (sc_start + sc_dur), 4)
			eff = round(sc_start + sc_dur + max(gap, 0.0) - sc_start, 4)
			eff = max(eff, sc_dur)
		else:
			eff = sc_dur
		effective_durations.append(eff)
	section_title_meta = _build_section_title_metadata(pid, scenes, effective_durations)

	enriched_scenes = []
	for idx, s in enumerate(scenes):
		sn = s.get('scene_num', 0)
		scene_media = media_by_scene.get(sn, [])
		scene_dur = float(s.get('duration', 0))
		eff_dur = effective_durations[idx]
		# Compute coverage: sum of effective clip durations (accounting for speed)
		covered = 0.0
		for m_dict in scene_media:
			ts = float(m_dict.get('trimStart', 0) or 0)
			te = m_dict.get('trimEnd')
			d = m_dict.get('duration')
			spd = float(m_dict.get('speed', 1.0) or 1.0)
			if spd <= 0:
				spd = 1.0
			if te is not None:
				covered += max(0, float(te) - ts) / spd
			elif d is not None:
				covered += max(0, float(d) - ts) / spd
			else:
				covered += 5.0
		# Subtract transition overlap between adjacent clips with non-cut transitions
		for i in range(len(scene_media) - 1):
			m_dict = scene_media[i]
			trans_type = m_dict.get('transitionType', 'cut')
			if trans_type and trans_type != 'cut':
				trans_dur = float(m_dict.get('transitionDuration', 0) or 0)
				covered -= trans_dur
		covered = max(0, covered)
		scene_section_title = section_title_meta.get(int(sn or 0))
		enriched_scenes.append({
			**s,
			'effectiveDuration': round(eff_dur, 3),
			'media': scene_media,
			'coveredSeconds': round(covered, 2),
			'remainingSeconds': round(max(0, eff_dur - covered), 2),
			'sectionTitle': scene_section_title.get('title') if scene_section_title else None,
			'sectionTitleOverlayDuration': float(scene_section_title.get('overlay_duration', 0.0)) if scene_section_title else 0.0,
			'sectionTitleElapsedBefore': float(scene_section_title.get('elapsed_before', 0.0)) if scene_section_title else 0.0,
			'sectionTitleSceneStart': bool(scene_section_title.get('is_section_start')) if scene_section_title else False,
		})

	return jsonify({
		'proceso1JobId': pid,
		'scenes': enriched_scenes,
		'totalScenes': len(scenes),
		'scenesWithMedia': len([s for s in enriched_scenes if s.get('media')]),
	})


# ---------------------------------------------------------------------------
# Audio — serve narration MP3
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/audio', methods=['GET'])
def get_audio(pid: int):
	get_or_create_job(pid)
	path = _get_final_mp3_path(pid)
	if not path:
		return jsonify({'error': 'Audio (final.mp3 de Proceso 2) no encontrado.'}), 404
	return send_file(str(path), mimetype='audio/mpeg', conditional=True)

