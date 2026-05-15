from __future__ import annotations

import json
import hashlib
import logging
import os
import re as _re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1SubprocessState
from aplicacion.models.proceso2 import Proceso2SubprocessState
from aplicacion.models.proceso3 import Proceso3SubprocessState
from aplicacion.models.proceso4 import (
	Proceso4AudioTrack,
	Proceso4GlobalAsset,
	Proceso4Job,
	Proceso4MusicTemplate,
	Proceso4MusicTemplateItem,
	Proceso4ReverbConfig,
	Proceso4SceneMedia,
	Proceso4SectionTrack,
	Proceso4SubprocessState,
)

from .ffmpeg_setup import FFPROBE_BIN, FFMPEG_BIN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_workspace_data_dir() -> Path:
	return Path(__file__).resolve().parents[4] / 'data'


def get_job_dir(proceso1_job_id: int) -> Path:
	return get_workspace_data_dir() / 'proceso4' / str(proceso1_job_id)


def get_or_create_job(proceso1_job_id: int) -> Proceso4Job:
	Proceso1Job.query.get_or_404(proceso1_job_id)
	job = Proceso4Job.query.get(proceso1_job_id)
	if job is None:
		job = Proceso4Job(proceso1_job_id=proceso1_job_id)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(proceso1_job_id: int, subprocess_key: str) -> Proceso4SubprocessState:
	state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key=subprocess_key,
	).first()
	if state is None:
		state = Proceso4SubprocessState(proceso1_job_id=proceso1_job_id, subprocess_key=subprocess_key)
		db.session.add(state)
	return state


def _save_state(state: Proceso4SubprocessState, payload: dict) -> Proceso4SubprocessState:
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


def _get_final_mp3_path(proceso1_job_id: int) -> Path | None:
	"""Return the Proceso2 concat final.mp3 path for this job if available."""
	concat_state = Proceso2SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id, subprocess_key='concat'
	).first()
	final_mp3 = (concat_state.output_payload or {}).get('finalMp3') if concat_state else None
	if not final_mp3:
		return None
	path = Path(str(final_mp3))
	return path if path.exists() else None


def _get_timeline_from_proceso3(proceso1_job_id: int) -> dict | None:
	"""Load timeline.json produced by Proceso 3."""
	state = Proceso3SubprocessState.query.filter_by(
		proceso1_job_id=proceso1_job_id,
		subprocess_key='timeline',
	).first()
	if not state or state.status != 'completed':
		return None
	tl = (state.output_payload or {}).get('timeline')
	if tl:
		return tl
	# Fallback: read from file
	tl_path = get_workspace_data_dir() / 'proceso3' / str(proceso1_job_id) / 'output' / 'timeline.json'
	if tl_path.exists():
		return json.loads(tl_path.read_text(encoding='utf-8'))
	return None


def _effective_clip_duration(clip: Proceso4SceneMedia) -> float:
	"""Return how many seconds this clip contributes to its scene.

	For videos with speed != 1.0, the trimmed duration is divided by speed.
	E.g. a 10s segment at 2x speed contributes 5s; at 0.5x it contributes 20s.
	"""
	s = clip.trim_start or 0.0
	e = clip.trim_end
	if e is not None:
		raw = max(0, e - s)
	elif clip.duration:
		raw = max(0, clip.duration - s)
	else:
		raw = 5.0  # fallback for images without explicit duration
	spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
	return raw / spd


def _get_scene_duration(pid: int, scene_num: int) -> float | None:
	"""Get the timeline duration for a specific scene from the imported P3 timeline."""
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='import_timeline'
	).first()
	if not import_state:
		return None
	tl = (import_state.output_payload or {}).get('timeline', {})
	for s in tl.get('scenes', []):
		if s.get('scene_num') == scene_num:
			return float(s.get('duration', 0))
	return None


def _get_scene_effective_duration(pid: int, scene_num: int) -> float | None:
	"""Get the EFFECTIVE duration for a scene (original + absorbed gap).

	This is the real duration the scene will occupy in the rendered video.
	It includes any inter-scene VAD gaps or section-boundary silences that
	the render loop absorbs by extending the scene clip.
	"""
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='import_timeline'
	).first()
	if not import_state:
		return None
	tl = (import_state.output_payload or {}).get('timeline', {})
	scenes = tl.get('scenes', [])
	for i, s in enumerate(scenes):
		if s.get('scene_num') == scene_num:
			s_start = float(s.get('start', 0.0))
			s_dur = float(s.get('duration', 5.0))
			if i + 1 < len(scenes):
				next_start = float(scenes[i + 1].get('start', 0.0))
				gap = round(next_start - (s_start + s_dur), 4)
				eff = round(s_start + s_dur + max(gap, 0.0) - s_start, 4)
				return max(eff, s_dur)
			else:
				return s_dur
	return None


def _get_video_duration(filepath: str) -> float | None:
	"""Get video duration in seconds. Tries ffprobe first, then parses MP4 moov atom."""
	# --- Attempt 1: ffprobe ---
	try:
		result = subprocess.run(
			[FFPROBE_BIN, '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
			capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
		)
		if result.returncode == 0 and result.stdout:
			info = json.loads(result.stdout)
			dur = float(info.get('format', {}).get('duration', 0))
			if dur > 0:
				logger.info(f"[P4] ffprobe detected duration {dur}s for {filepath}")
				return dur
	except Exception as e:
		logger.warning(f"[P4] ffprobe attempt failed for {filepath}: {e}")

	# --- Attempt 2: ffmpeg -i (duration in stderr) ---
	try:
		import re
		result = subprocess.run(
			[FFMPEG_BIN, '-i', filepath],
			capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
		)
		match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', result.stderr)
		if match:
			h, m, s = match.groups()
			dur = int(h) * 3600 + int(m) * 60 + float(s)
			if dur > 0:
				logger.info(f"[P4] ffmpeg -i detected duration {dur}s for {filepath}")
				return dur
	except Exception as e:
		logger.warning(f"[P4] ffmpeg -i attempt failed for {filepath}: {e}")

	# --- Attempt 3: Parse MP4 moov/mvhd atom (pure Python) ---
	try:
		dur = _parse_mp4_duration(filepath)
		if dur and dur > 0:
			logger.info(f"[P4] MP4 parser detected duration {dur}s for {filepath}")
			return dur
	except Exception as e:
		logger.warning(f"[P4] MP4 parser failed for {filepath}: {e}")

	logger.error(f"[P4] Could NOT detect duration for {filepath} — all methods failed!")
	return None


def _parse_mp4_duration(filepath: str) -> float | None:
	"""Parse MP4 moov/mvhd atom to get duration without external tools."""
	import struct
	with open(filepath, 'rb') as f:
		while True:
			header = f.read(8)
			if len(header) < 8:
				break
			size = struct.unpack('>I', header[:4])[0]
			box_type = header[4:8]
			if size == 0:
				break
			if size == 1:
				ext_size = f.read(8)
				if len(ext_size) < 8:
					break
				size = struct.unpack('>Q', ext_size)[0]

			if box_type == b'moov':
				# Recurse into moov to find mvhd
				continue  # children follow immediately
			elif box_type == b'mvhd':
				version = struct.unpack('B', f.read(1))[0]
				f.read(3)  # flags
				if version == 0:
					f.read(4)  # creation_time
					f.read(4)  # modification_time
					timescale = struct.unpack('>I', f.read(4))[0]
					duration = struct.unpack('>I', f.read(4))[0]
				else:
					f.read(8)  # creation_time
					f.read(8)  # modification_time
					timescale = struct.unpack('>I', f.read(4))[0]
					duration = struct.unpack('>Q', f.read(8))[0]
				if timescale > 0:
					return duration / timescale
				return None
			else:
				# Skip to next box
				remaining = size - 8
				if remaining > 0:
					f.seek(remaining, 1)
	return None


# ---------------------------------------------------------------------------
# Proxy generation helper (low-res preview for Timeline)
# ---------------------------------------------------------------------------

def _generate_proxy(original_path: str, record_id: int) -> str | None:
	"""Generate a low-res 480p proxy video for preview.

	Runs in the background thread so the upload response isn't blocked.
	Returns the proxy path string, or None on failure.
	"""
	try:
		orig = Path(original_path)
		proxy_name = f"{orig.stem}_proxy.mp4"
		proxy_path = orig.parent / proxy_name

		# Scale to 480p height, keep aspect, divisible by 2
		cmd = [
			FFMPEG_BIN,
			'-y',
			'-i', str(orig),
			'-vf', 'scale=-2:480',
			'-c:v', 'libx264',
			'-preset', 'ultrafast',
			'-crf', '30',
			'-an',            # strip audio
			'-movflags', '+faststart',
			str(proxy_path),
		]
		result = subprocess.run(cmd, capture_output=True, timeout=120)
		if result.returncode == 0 and proxy_path.exists():
			logger.info(f"[P4] Proxy generated for media {record_id}: {proxy_path}")
			return str(proxy_path)
		else:
			logger.warning(f"[P4] Proxy generation failed for media {record_id}: "
			               f"rc={result.returncode} stderr={result.stderr[:300] if result.stderr else ''}")
	except Exception as e:
		logger.warning(f"[P4] Proxy generation error for media {record_id}: {e}")
	return None


def _generate_proxy_async(original_path: str, record_id: int, app):
	"""Generate proxy in a background thread and update the DB record."""
	import threading

	def _worker():
		with app.app_context():
			proxy = _generate_proxy(original_path, record_id)
			if proxy:
				rec = Proceso4SceneMedia.query.get(record_id)
				if rec:
					rec.proxy_path = proxy
					db.session.commit()

	t = threading.Thread(target=_worker, daemon=True)
	t.start()


# ---------------------------------------------------------------------------
# Global assets helpers
# ---------------------------------------------------------------------------

def get_global_assets_dir() -> Path:
	d = get_workspace_data_dir() / 'proceso4' / 'global'
	d.mkdir(parents=True, exist_ok=True)
	return d


def _get_indice_data(proceso1_job_id: int) -> dict:
	"""Return ÍNDICE metadata for this project.

	Searches multiple sources in priority order:
	  1. Proceso1SubprocessState  subproceso2 → estructura.subtemas[].titulo  (DB, always available)
	  2. Session JSON  p2_estructura.subtemas[].titulo  (legacy Streamlit projects)
	  3. Fallback: empty list

	Returns a dict with:
	  - 'subtemas': list of subtema title strings
	  - 'indice_text': formatted "In this video..." paragraph
	"""
	from aplicacion.models.proceso1 import Proceso1SubprocessState as P1State

	subtemas: list[str] = []
	indice_text: str = ''

	# ── Source 1: Proceso1 DB (subproceso2 → estructura) ──────────────────
	try:
		p1_state = P1State.query.filter_by(
			job_id=proceso1_job_id, subprocess_key='subproceso2'
		).first()
		if p1_state and p1_state.output_payload:
			estructura = (p1_state.output_payload or {}).get('estructura', {})
			for s in estructura.get('subtemas', []):
				t = (s.get('titulo', '') if isinstance(s, dict) else str(s)).strip()
				if t:
					subtemas.append(t)
	except Exception as e:
		logger.warning(f'[P4] Could not read P1 estructura for pid={proceso1_job_id}: {e}')

	# ── Source 2: Session JSON (legacy fallback) ──────────────────────────
	if not subtemas:
		session_path = get_workspace_data_dir() / 'projects' / f'{proceso1_job_id}_session.json'
		if session_path.exists():
			try:
				sess = json.loads(session_path.read_text(encoding='utf-8'))
				estrutura = sess.get('p2_estructura') or {}
				for s in estrutura.get('subtemas', []):
					t = (s.get('titulo', '') if isinstance(s, dict) else str(s)).strip()
					if t:
						subtemas.append(t)

				ensamblaje = sess.get('p3_ensamblaje_inputs') or {}
				indice_text = (ensamblaje.get('indice') or '').strip()
			except Exception as e:
				logger.warning(f'[P4] Could not read session JSON for pid={proceso1_job_id}: {e}')

	# ── Build indice_text from subtemas if not already set ────────────────
	if not indice_text and subtemas:
		if len(subtemas) >= 2:
			indice_text = 'In this video: ' + ', '.join(subtemas[:-1]) + ' and ' + subtemas[-1]
		else:
			indice_text = 'In this video: ' + (subtemas[0] if subtemas else '')

	return {'subtemas': subtemas, 'indice_text': indice_text}


SECTION_TITLE_OVERLAY_DURATION = 3.5


def _compute_effective_durations_from_scenes(scenes: list[dict]) -> list[float]:
	"""Mirror the render-loop duration logic for timeline-derived scenes."""
	effective_durations: list[float] = []
	for idx, scene in enumerate(scenes or []):
		scene_start = float(scene.get('start', 0.0))
		scene_duration = float(scene.get('duration', 5.0))
		if idx + 1 < len(scenes):
			next_start = float(scenes[idx + 1].get('start', 0.0))
			gap = round(next_start - (scene_start + scene_duration), 4)
			eff = round(scene_start + scene_duration + max(gap, 0.0) - scene_start, 4)
			eff = max(eff, scene_duration)
		else:
			eff = scene_duration
		effective_durations.append(eff)
	return effective_durations


def _resolve_section_title(section: object, subtemas: list[str]) -> str | None:
	"""Map a timeline section key like parte2/subtema_2 to its human title."""
	key = str(section or '').strip().lower()
	if not key:
		return None
	match = _re.match(r'^(?:parte|subtema)_?(\d+)$', key)
	if not match:
		return None
	try:
		index = int(match.group(1)) - 1
	except ValueError:
		return None
	if index < 0 or index >= len(subtemas):
		return None
	title = str(subtemas[index] or '').strip()
	return title or None


def _build_section_title_metadata(
	proceso1_job_id: int,
	scenes: list[dict],
	effective_durations: list[float] | None = None,
) -> dict[int, dict]:
	"""Return per-scene overlay metadata for animated section titles.

	Only body sections mapped to real subtema titles receive metadata. Intro and
	cierre keep their current look to avoid colliding with existing special
	overlays like indice and pregunta capciosa.
	"""
	scenes = list(scenes or [])
	if not scenes:
		return {}
	effective_durations = effective_durations or _compute_effective_durations_from_scenes(scenes)
	subtemas = list((_get_indice_data(proceso1_job_id) or {}).get('subtemas') or [])
	if not subtemas:
		return {}

	metadata_by_scene: dict[int, dict] = {}
	for idx, scene in enumerate(scenes):
		section = str(scene.get('section', '') or '')
		prev_section = str(scenes[idx - 1].get('section', '') or '') if idx > 0 else ''
		if idx > 0 and section == prev_section:
			continue

		title = _resolve_section_title(section, subtemas)
		if not title:
			continue

		section_start = float(scene.get('start', 0.0))
		last_idx = idx
		while last_idx + 1 < len(scenes) and str(scenes[last_idx + 1].get('section', '') or '') == section:
			last_idx += 1
		section_render_end = float(scenes[last_idx].get('start', 0.0)) + float(effective_durations[last_idx])
		overlay_duration = round(
			max(0.0, min(SECTION_TITLE_OVERLAY_DURATION, section_render_end - section_start)),
			3,
		)
		if overlay_duration <= 0.05:
			continue

		overlay_end = section_start + overlay_duration
		for section_scene_idx in range(idx, last_idx + 1):
			section_scene = scenes[section_scene_idx]
			scene_num = int(section_scene.get('scene_num', 0) or 0)
			scene_start = float(section_scene.get('start', 0.0))
			scene_render_end = scene_start + float(effective_durations[section_scene_idx])
			if scene_start >= overlay_end or scene_render_end <= section_start:
				continue
			metadata_by_scene[scene_num] = {
				'title': title,
				'section': section,
				'section_start': round(section_start, 3),
				'overlay_duration': overlay_duration,
				'elapsed_before': round(max(0.0, scene_start - section_start), 3),
				'is_section_start': section_scene_idx == idx,
			}

	return metadata_by_scene

