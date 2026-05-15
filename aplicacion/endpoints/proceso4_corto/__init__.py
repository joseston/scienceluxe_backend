"""
Proceso 4 Corto — Short Video Assembly (Vertical 9:16)
=======================================================
Endpoints for assembling short-form vertical videos.
Imports timeline from Proceso 3 Corto, allows media upload per scene,
editing params, audio tracks, and video rendering via FFmpeg at 1080×1920.

Reuses FFmpeg utilities from Proceso 4 (largo).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from aplicacion import db
from aplicacion.models.proceso1_corto import Proceso1CortoJob
from aplicacion.models.proceso2_corto import Proceso2CortoSubprocessState
from aplicacion.models.proceso3_corto import Proceso3CortoSubprocessState
from aplicacion.models.proceso4_corto import (
	Proceso4CortoAudioTrack,
	Proceso4CortoJob,
	Proceso4CortoSceneMedia,
	Proceso4CortoSubprocessState,
)

from .prompt_templates_corto import (
	build_text_to_video_prompt_corto,
	build_text_to_image_prompt_corto,
	build_image_to_video_prompt_corto,
	DEFAULT_ESTILO_CANAL_CORTO,
)

# Reuse FFmpeg utilities from P4 largo
from aplicacion.endpoints.proceso4 import (
	FFMPEG_BIN,
	FFPROBE_BIN,
	VIDEO_ENCODER,
	USE_NVENC,
	_get_video_duration,
	_parse_mp4_duration,
	_generate_proxy,
)

proceso4_corto_bp = Blueprint('proceso4_corto', __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Vertical 9:16
# ---------------------------------------------------------------------------
WIDTH  = 1080
HEIGHT = 1920
_SCALE_VF_CORTO = f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_workspace_data_dir() -> Path:
	return Path(__file__).resolve().parents[4] / 'data'


def get_job_dir(pid: int) -> Path:
	return get_workspace_data_dir() / 'proceso4_corto' / str(pid)


def get_or_create_job(pid: int) -> Proceso4CortoJob:
	Proceso1CortoJob.query.get_or_404(pid)
	job = Proceso4CortoJob.query.get(pid)
	if job is None:
		job = Proceso4CortoJob(proceso1_corto_job_id=pid)
		db.session.add(job)
	return job


def get_or_create_subprocess_state(pid: int, key: str) -> Proceso4CortoSubprocessState:
	state = Proceso4CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key=key,
	).first()
	if state is None:
		state = Proceso4CortoSubprocessState(proceso1_corto_job_id=pid, subprocess_key=key)
		db.session.add(state)
	return state


def _save_state(state: Proceso4CortoSubprocessState, payload: dict) -> Proceso4CortoSubprocessState:
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


def _get_final_audio_path(pid: int) -> Path | None:
	"""Return the P2 Corto speech audio path (speed-adjusted or audio_input)."""
	# Try speed subprocess first (has the speed-adjusted file)
	speed_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='speed'
	).first()
	if speed_state and (speed_state.output_payload or {}).get('speedFile'):
		p = Path(str(speed_state.output_payload['speedFile']))
		if p.exists():
			return p

	# Fallback: audio_input subprocess
	ai_state = Proceso2CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='audio_input'
	).first()
	if ai_state and (ai_state.output_payload or {}).get('audioPath'):
		p = Path(str(ai_state.output_payload['audioPath']))
		if p.exists():
			return p

	return None


def _get_timeline_from_proceso3_corto(pid: int) -> dict | None:
	"""Load timeline from Proceso 3 Corto."""
	state = Proceso3CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='timeline',
	).first()
	if not state or state.status != 'completed':
		return None
	tl = (state.output_payload or {}).get('timeline')
	if tl:
		return tl
	# Fallback: read from file
	tl_path = get_workspace_data_dir() / 'proceso3_corto' / str(pid) / 'output' / 'timeline.json'
	if tl_path.exists():
		return json.loads(tl_path.read_text(encoding='utf-8'))
	return None


def _effective_clip_duration(clip: Proceso4CortoSceneMedia) -> float:
	s = clip.trim_start or 0.0
	e = clip.trim_end
	if e is not None:
		raw = max(0, e - s)
	elif clip.duration:
		raw = max(0, clip.duration - s)
	else:
		raw = 5.0
	spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
	return raw / spd


def _secs_to_ass_time(s: float) -> str:
	"""Convert seconds to ASS timestamp format 'H:MM:SS.cc' (centiseconds)."""
	h = int(s // 3600)
	m = int((s % 3600) // 60)
	sec = int(s % 60)
	cs = int(round((s - int(s)) * 100))
	return f'{h}:{m:02d}:{sec:02d}.{cs:02d}'


def _generate_ass_file(subtitles: list[dict], out_path: str, font_path: str) -> None:
	"""Generate an ASS subtitle file with Montserrat Black styling for 9:16 vertical video.

	Subtitle style:
	  - Font: Montserrat Black (weight 900)
	  - Size: 48pt (tuned for 1080×1920)
	  - Color: White text, black outline + shadow
	  - Position: Centered at bottom (Alignment=2, MarginV=80)
	  - Uppercase transform
	"""
	# Extract just the font filename for ASS (requires font to be accessible to FFmpeg)
	font_name = 'Montserrat'

	header = (
		'[Script Info]\n'
		'ScriptType: v4.00+\n'
		'PlayResX: 1080\n'
		'PlayResY: 1920\n'
		'WrapStyle: 0\n'
		'ScaledBorderAndShadow: yes\n'
		'\n'
		'[V4+ Styles]\n'
		'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
		'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, '
		'BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
		f'Style: Default,{font_name},48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,'
		'1,0,0,0,100,100,1,0,1,3,2,2,40,40,80,1\n'
		'\n'
		'[Events]\n'
		'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
	)

	lines: list[str] = [header]
	for sub in subtitles:
		start = _secs_to_ass_time(float(sub.get('start', 0)))
		end = _secs_to_ass_time(float(sub.get('end', 0)))
		text = str(sub.get('text', '')).upper().replace('\n', '\\N')
		lines.append(
			f'Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n'
		)

	with open(out_path, 'w', encoding='utf-8') as f:
		f.writelines(lines)


# ---------------------------------------------------------------------------
# FFmpeg helpers (adapted for vertical)
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd: list, timeout: int = 180, tag: str = '') -> bool:
	result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
	if result.returncode != 0:
		logger.error(f"[P4C]{' ' + tag if tag else ''} FFmpeg failed (rc={result.returncode}): {result.stderr[-400:]}")
		return False
	return True


def _file_ok(path: str) -> bool:
	p = Path(path)
	return p.exists() and p.stat().st_size > 0


def _build_black_scene(dur: float, work_dir: Path, sn: int) -> str:
	out = str(work_dir / f'scene_{sn}.mp4')
	_run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r=30',
		'-t', str(dur),
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'black S{sn}')
	return out


def _get_clip_duration(path: str) -> float:
	try:
		result = subprocess.run(
			[FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
			 '-of', 'default=noprint_wrappers=1:nokey=1', path],
			capture_output=True, text=True, timeout=30,
		)
		return float(result.stdout.strip())
	except Exception:
		return 0.0


def _pad_to_duration(clip_path: str, target: float, work_dir: Path, sn: int, tag: str = '') -> str:
	actual = _get_clip_duration(clip_path)
	if actual <= 0:
		return clip_path

	# Overshoot: trim
	if actual > target + 0.04:
		trimmed = str(work_dir / f'scene_{sn}_trimmed.mp4')
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y', '-i', clip_path, '-t', str(target), '-c', 'copy', '-an', trimmed,
		], tag=f'{tag} trim')
		if ok and _file_ok(trimmed):
			shutil.move(trimmed, clip_path)
		return clip_path

	# Within tolerance
	if actual >= target - 0.04:
		return clip_path

	shortfall = target - actual
	padded = str(work_dir / f'scene_{sn}_padded.mp4')

	if shortfall <= 1.0 and actual > 0.5:
		pts = target / actual
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y', '-i', clip_path,
			'-vf', f'{_SCALE_VF_CORTO},setpts={pts:.6f}*PTS',
			'-r', '30', '-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-an',
			padded,
		], tag=f'{tag} slowmo')
	else:
		# Fade to black + black padding
		fade_dur = min(0.5, actual * 0.3)
		fade_start = max(0, actual - fade_dur)
		faded = str(work_dir / f'scene_{sn}_faded.mp4')
		ok_fade = _run_ffmpeg([
			FFMPEG_BIN, '-y', '-i', clip_path,
			'-vf', f'fade=t=out:st={fade_start:.4f}:d={fade_dur:.4f}',
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			faded,
		], tag=f'{tag} fade-out')

		black = str(work_dir / f'scene_{sn}_black_tail.mp4')
		ok_black = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r=30',
			'-t', str(shortfall),
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			black,
		], tag=f'{tag} black tail')

		ok = False
		if ok_fade and _file_ok(faded) and ok_black and _file_ok(black):
			concat_f = work_dir / f'scene_{sn}_pad_concat.txt'
			with open(concat_f, 'w', encoding='utf-8') as fh:
				fh.write(f"file '{faded}'\n")
				fh.write(f"file '{black}'\n")
			ok = _run_ffmpeg([
				FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
				'-i', str(concat_f), '-c', 'copy', '-an', padded,
			], tag=f'{tag} concat fade+black')

	if ok and _file_ok(padded):
		shutil.move(padded, clip_path)
	return clip_path


def _build_single_clip(clip: Proceso4CortoSceneMedia, scene_dur: float,
                       work_dir: Path, sn: int) -> str:
	out = str(work_dir / f'scene_{sn}.mp4')

	if clip.media_type == 'image':
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-loop', '1', '-i', clip.file_path,
			'-t', str(scene_dur),
			'-vf', _SCALE_VF_CORTO,
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			out,
		], tag=f'S{sn} image')
	else:
		spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
		trim_start = clip.trim_start or 0.0
		trim_end = clip.trim_end if clip.trim_end else (trim_start + scene_dur * spd)
		raw_dur = trim_end - trim_start

		if abs(spd - 1.0) > 0.01:
			pts = 1.0 / spd
			vf = f'{_SCALE_VF_CORTO},setpts={pts:.6f}*PTS'
		else:
			vf = _SCALE_VF_CORTO

		input_args = (['-ss', str(trim_start)] if trim_start > 0 else []) + ['-i', clip.file_path]
		cmd = [
			FFMPEG_BIN, '-y',
			*input_args,
			'-t', str(raw_dur),
			'-vf', vf,
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		]
		if abs(spd - 1.0) > 0.01:
			cmd.extend(['-t', str(scene_dur)])
		cmd.append(out)
		ok = _run_ffmpeg(cmd, tag=f'S{sn} video spd={spd}x')

	if not ok or not _file_ok(out):
		_build_black_scene(scene_dur, work_dir, sn)
		return out

	_pad_to_duration(out, scene_dur, work_dir, sn, tag=f'S{sn}')
	return out


def _build_multi_clip(media_list: list[Proceso4CortoSceneMedia], scene_dur: float,
                      work_dir: Path, sn: int) -> str:
	"""Build a multi-clip scene by concatenating individual clips."""
	sub_clips = []
	for i, clip in enumerate(media_list):
		sub_dur = _effective_clip_duration(clip)
		sub_out = str(work_dir / f'scene_{sn}_clip{i}.mp4')

		if clip.media_type == 'image':
			ok = _run_ffmpeg([
				FFMPEG_BIN, '-y',
				'-loop', '1', '-i', clip.file_path,
				'-t', str(sub_dur),
				'-vf', _SCALE_VF_CORTO,
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				sub_out,
			], tag=f'S{sn} multi-clip{i} image')
		else:
			spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
			ts = clip.trim_start or 0.0
			te = clip.trim_end or (ts + sub_dur * spd)
			raw = te - ts
			if abs(spd - 1.0) > 0.01:
				pts = 1.0 / spd
				vf = f'{_SCALE_VF_CORTO},setpts={pts:.6f}*PTS'
			else:
				vf = _SCALE_VF_CORTO
			input_args = (['-ss', str(ts)] if ts > 0 else []) + ['-i', clip.file_path]
			ok = _run_ffmpeg([
				FFMPEG_BIN, '-y', *input_args,
				'-t', str(raw), '-vf', vf,
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				sub_out,
			], tag=f'S{sn} multi-clip{i} video')

		if _file_ok(sub_out):
			sub_clips.append(sub_out)

	if not sub_clips:
		return _build_black_scene(scene_dur, work_dir, sn)

	# Concat sub-clips
	out = str(work_dir / f'scene_{sn}.mp4')
	concat_f = work_dir / f'scene_{sn}_multiconcat.txt'
	with open(concat_f, 'w', encoding='utf-8') as f:
		for cp in sub_clips:
			f.write(f"file '{cp}'\n")

	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
		'-i', str(concat_f), '-c', 'copy', '-an', out,
	], tag=f'S{sn} multi-concat')

	if not ok or not _file_ok(out):
		return _build_black_scene(scene_dur, work_dir, sn)

	_pad_to_duration(out, scene_dur, work_dir, sn, tag=f'S{sn}')
	return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/init', methods=['POST'])
def init_job(pid: int):
	job = get_or_create_job(pid)
	job_dir = get_job_dir(pid)
	(job_dir / 'media').mkdir(parents=True, exist_ok=True)
	(job_dir / 'audio_tracks').mkdir(parents=True, exist_ok=True)
	(job_dir / 'output').mkdir(parents=True, exist_ok=True)
	db.session.commit()

	# Auto-import timeline from P3 Corto
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	if import_state.status != 'completed':
		tl = _get_timeline_from_proceso3_corto(pid)
		if tl:
			_save_state(import_state, {'status': 'completed', 'output': {'timeline': tl}})
		else:
			_save_state(import_state, {'status': 'draft'})
	db.session.commit()

	return jsonify(job.to_dict())


@proceso4_corto_bp.route('/jobs/<int:pid>', methods=['GET'])
def get_job(pid: int):
	job = get_or_create_job(pid)
	db.session.commit()
	return jsonify(job.to_dict())


@proceso4_corto_bp.route('/jobs/<int:pid>/subprocesses', methods=['GET'])
def list_subprocess_states(pid: int):
	get_or_create_job(pid)
	states = (
		Proceso4CortoSubprocessState.query
		.filter_by(proceso1_corto_job_id=pid)
		.order_by(Proceso4CortoSubprocessState.id)
		.all()
	)
	db.session.commit()
	return jsonify([s.to_dict() for s in states])


@proceso4_corto_bp.route('/jobs/<int:pid>/subprocesses/<string:key>', methods=['GET'])
def get_subprocess_state(pid: int, key: str):
	get_or_create_job(pid)
	state = get_or_create_subprocess_state(pid, key)
	db.session.commit()
	return jsonify(state.to_dict())


@proceso4_corto_bp.route('/jobs/<int:pid>/subprocesses/<string:key>', methods=['PUT'])
def update_subprocess_state(pid: int, key: str):
	get_or_create_job(pid)
	state = get_or_create_subprocess_state(pid, key)
	body = request.get_json(force=True) or {}
	saved = _save_state(state, body)
	return jsonify(saved.to_dict())


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/timeline', methods=['GET'])
def get_timeline(pid: int):
	get_or_create_job(pid)
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()

	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'Timeline no importado. Completa primero el Proceso 3 Corto (Timeline).'}), 404

	scenes = tl.get('scenes', [])

	# Attach media info per scene
	all_media = Proceso4CortoSceneMedia.query.filter_by(proceso1_corto_job_id=pid).order_by(
		Proceso4CortoSceneMedia.scene_num, Proceso4CortoSceneMedia.clip_index
	).all()
	media_by_scene: dict[int, list[dict]] = {}
	for m in all_media:
		media_by_scene.setdefault(m.scene_num, []).append(m.to_dict())

	# Pre-compute effective durations
	effective_durations: list[float] = []
	for i, sc in enumerate(scenes):
		sc_start = float(sc.get('start', 0.0))
		sc_dur = float(sc.get('duration', 5.0))
		if i + 1 < len(scenes):
			next_start = float(scenes[i + 1].get('start', 0.0))
			gap = round(next_start - (sc_start + sc_dur), 4)
			eff = round(sc_start + sc_dur + max(gap, 0.0) - sc_start, 4)
			eff = max(eff, sc_dur)
		else:
			eff = sc_dur
		effective_durations.append(eff)

	enriched_scenes = []
	for idx, s in enumerate(scenes):
		sn = s.get('scene_num', 0)
		scene_media = media_by_scene.get(sn, [])
		eff_dur = effective_durations[idx]
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
		covered = max(0, covered)
		enriched_scenes.append({
			**s,
			'effectiveDuration': round(eff_dur, 3),
			'media': scene_media,
			'coveredSeconds': round(covered, 2),
			'remainingSeconds': round(max(0, eff_dur - covered), 2),
		})

	return jsonify({
		'proceso1CortoJobId': pid,
		'scenes': enriched_scenes,
		'totalScenes': len(scenes),
		'scenesWithMedia': len([s for s in enriched_scenes if s.get('media')]),
	})


# ---------------------------------------------------------------------------
# Audio — serve narration
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/audio', methods=['GET'])
def get_audio(pid: int):
	get_or_create_job(pid)
	path = _get_final_audio_path(pid)
	if not path:
		return jsonify({'error': 'Audio de Proceso 2 Corto no encontrado.'}), 404
	return send_file(str(path), mimetype='audio/mpeg', conditional=True)


# ---------------------------------------------------------------------------
# Media Upload per Scene
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media', methods=['POST'])
def upload_scene_media(pid: int, scene_num: int):
	get_or_create_job(pid)

	if 'file' not in request.files:
		return jsonify({'error': 'No file in request.'}), 400

	f = request.files['file']
	if not f.filename:
		return jsonify({'error': 'Empty filename.'}), 400

	ext = (f.filename.rsplit('.', 1)[-1] if '.' in f.filename else '').lower()
	video_exts = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
	image_exts = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}

	if ext in video_exts:
		media_type = 'video'
	elif ext in image_exts:
		media_type = 'image'
	else:
		return jsonify({'error': f'Extensión no soportada: .{ext}'}), 400

	# Determine clip_index
	existing_clips = Proceso4CortoSceneMedia.query.filter_by(
		proceso1_corto_job_id=pid, scene_num=scene_num
	).order_by(Proceso4CortoSceneMedia.clip_index).all()
	clip_index = (max(ec.clip_index for ec in existing_clips) + 1) if existing_clips else 0

	# Already-covered time
	already_covered = sum(_effective_clip_duration(ec) for ec in existing_clips)

	# Get scene duration from import state
	import_state = Proceso4CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='import_timeline'
	).first()
	scene_duration = 5.0
	if import_state:
		tl = (import_state.output_payload or {}).get('timeline', {})
		for s in tl.get('scenes', []):
			if s.get('scene_num') == scene_num:
				scene_duration = float(s.get('duration', 5.0))
				break
	remaining = max(0, scene_duration - already_covered)

	# Save file
	media_dir = get_job_dir(pid) / 'media'
	media_dir.mkdir(parents=True, exist_ok=True)
	safe_name = f"s{scene_num}_c{clip_index}_{uuid.uuid4().hex[:8]}.{ext}"
	out_path = str(media_dir / safe_name)
	f.save(out_path)

	if media_type == 'video':
		detected = _get_video_duration(out_path) or 5.0
		duration = detected
		trim_end = detected
	else:
		img_dur = max(2.0, remaining) if remaining > 0 else 5.0
		duration = img_dur
		trim_end = img_dur

	record = Proceso4CortoSceneMedia(
		proceso1_corto_job_id=pid,
		scene_num=scene_num,
		clip_index=clip_index,
		media_type=media_type,
		original_filename=f.filename,
		file_path=out_path,
		duration=duration,
		trim_start=0.0,
		trim_end=trim_end,
		transition_type='cut',
		transition_duration=0.0,
	)
	db.session.add(record)
	db.session.commit()

	logger.info(f"[P4C] pid={pid} scene={scene_num} clip={clip_index} type={media_type} file={f.filename}")

	# Generate proxy for videos
	from flask import current_app
	if media_type == 'video':
		import threading
		_app = current_app._get_current_object()
		_rid = record.id
		def _proxy_worker():
			with _app.app_context():
				proxy = _generate_proxy(out_path, _rid)
				if proxy:
					rec = Proceso4CortoSceneMedia.query.get(_rid)
					if rec:
						rec.proxy_path = proxy
						db.session.commit()
		threading.Thread(target=_proxy_worker, daemon=True).start()

	return jsonify(record.to_dict()), 201


@proceso4_corto_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media', methods=['GET'])
def list_scene_media(pid: int, scene_num: int):
	get_or_create_job(pid)
	media = Proceso4CortoSceneMedia.query.filter_by(
		proceso1_corto_job_id=pid, scene_num=scene_num
	).order_by(Proceso4CortoSceneMedia.clip_index).all()
	db.session.commit()
	return jsonify([m.to_dict() for m in media])


@proceso4_corto_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media/<int:media_id>', methods=['PUT'])
def update_scene_media(pid: int, scene_num: int, media_id: int):
	get_or_create_job(pid)
	record = Proceso4CortoSceneMedia.query.get_or_404(media_id)
	if record.proceso1_corto_job_id != pid or record.scene_num != scene_num:
		return jsonify({'error': 'Media not found for this scene.'}), 404

	body = request.get_json(force=True) or {}

	if 'trimStart' in body:
		record.trim_start = float(body['trimStart'])
	if 'trimEnd' in body:
		new_trim_end = float(body['trimEnd']) if body['trimEnd'] is not None else None
		if new_trim_end is not None and record.media_type == 'video':
			if record.duration and new_trim_end > record.duration:
				return jsonify({'error': f'trim_end ({new_trim_end}s) cannot exceed duration ({record.duration}s)'}), 400
		record.trim_end = new_trim_end
	if 'transitionType' in body:
		record.transition_type = str(body['transitionType'])
	if 'transitionDuration' in body:
		record.transition_duration = float(body['transitionDuration'])
	if 'speed' in body:
		new_speed = float(body['speed'])
		if new_speed < 0.25 or new_speed > 4.0:
			return jsonify({'error': f'Speed ({new_speed}) must be between 0.25 and 4.0'}), 400
		record.speed = new_speed
	if 'displayDuration' in body and record.media_type == 'image':
		dur = float(body['displayDuration'])
		record.trim_start = 0.0
		record.trim_end = max(0.5, dur)
		record.duration = record.trim_end

	db.session.commit()
	return jsonify(record.to_dict())


@proceso4_corto_bp.route('/jobs/<int:pid>/scenes/<int:scene_num>/media/<int:media_id>', methods=['DELETE'])
def delete_scene_media(pid: int, scene_num: int, media_id: int):
	get_or_create_job(pid)
	record = Proceso4CortoSceneMedia.query.get_or_404(media_id)
	if record.proceso1_corto_job_id != pid or record.scene_num != scene_num:
		return jsonify({'error': 'Media not found for this scene.'}), 404

	try:
		fp = Path(record.file_path)
		if fp.exists():
			fp.unlink()
	except Exception as e:
		logger.warning(f"Could not delete file {record.file_path}: {e}")
	try:
		if record.proxy_path:
			pp = Path(record.proxy_path)
			if pp.exists():
				pp.unlink()
	except Exception as e:
		logger.warning(f"Could not delete proxy {record.proxy_path}: {e}")

	db.session.delete(record)
	db.session.commit()
	return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Serve media files
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/media-file/<int:media_id>', methods=['GET'])
def serve_media_file(pid: int, media_id: int):
	record = Proceso4CortoSceneMedia.query.get_or_404(media_id)
	if record.proceso1_corto_job_id != pid:
		return jsonify({'error': 'Not found'}), 404
	path = Path(record.file_path)
	if not path.exists():
		return jsonify({'error': 'File not found on disk'}), 404

	ext = path.suffix.lower()
	mime_map = {
		'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.avi': 'video/x-msvideo',
		'.mkv': 'video/x-matroska', '.webm': 'video/webm',
		'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
		'.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
	}
	return send_file(str(path), mimetype=mime_map.get(ext, 'application/octet-stream'), conditional=True)


@proceso4_corto_bp.route('/jobs/<int:pid>/media-file/<int:media_id>/proxy', methods=['GET'])
def serve_media_proxy(pid: int, media_id: int):
	record = Proceso4CortoSceneMedia.query.get_or_404(media_id)
	if record.proceso1_corto_job_id != pid:
		return jsonify({'error': 'Not found'}), 404

	if record.proxy_path:
		pp = Path(record.proxy_path)
		if pp.exists():
			return send_file(str(pp), mimetype='video/mp4', conditional=True)

	path = Path(record.file_path)
	if not path.exists():
		return jsonify({'error': 'File not found on disk'}), 404
	ext = path.suffix.lower()
	mime_map = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm'}
	return send_file(str(path), mimetype=mime_map.get(ext, 'video/mp4'), conditional=True)


# ---------------------------------------------------------------------------
# Audio Tracks (optional music)
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/audio-tracks', methods=['POST'])
def upload_audio_track(pid: int):
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

	record = Proceso4CortoAudioTrack(
		proceso1_corto_job_id=pid,
		track_type=track_type,
		original_filename=f.filename,
		file_path=str(out_path),
		start_time=start_time,
		volume=volume,
	)
	db.session.add(record)
	db.session.commit()
	return jsonify(record.to_dict()), 201


@proceso4_corto_bp.route('/jobs/<int:pid>/audio-tracks', methods=['GET'])
def list_audio_tracks(pid: int):
	get_or_create_job(pid)
	tracks = Proceso4CortoAudioTrack.query.filter_by(proceso1_corto_job_id=pid).all()
	db.session.commit()
	return jsonify([t.to_dict() for t in tracks])


@proceso4_corto_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>', methods=['PUT'])
def update_audio_track(pid: int, track_id: int):
	get_or_create_job(pid)
	record = Proceso4CortoAudioTrack.query.get_or_404(track_id)
	if record.proceso1_corto_job_id != pid:
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


@proceso4_corto_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>', methods=['DELETE'])
def delete_audio_track(pid: int, track_id: int):
	get_or_create_job(pid)
	record = Proceso4CortoAudioTrack.query.get_or_404(track_id)
	if record.proceso1_corto_job_id != pid:
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


@proceso4_corto_bp.route('/jobs/<int:pid>/audio-tracks/<int:track_id>/file', methods=['GET'])
def serve_audio_track_file(pid: int, track_id: int):
	get_or_create_job(pid)
	record = Proceso4CortoAudioTrack.query.get_or_404(track_id)
	if record.proceso1_corto_job_id != pid:
		return jsonify({'error': 'Not found'}), 404
	fp = Path(record.file_path)
	if not fp.exists():
		return jsonify({'error': 'Audio track file not found on disk'}), 404
	return send_file(str(fp), mimetype='audio/mpeg', conditional=True)


# ---------------------------------------------------------------------------
# Prompt Station
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/prompt-station', methods=['GET'])
def get_prompt_station(pid: int):
	get_or_create_job(pid)
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()

	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'Timeline no importado.'}), 404

	scenes = tl.get('scenes', [])

	# Get estilo_canal from config subprocess
	config_state = Proceso4CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='config'
	).first()
	estilo_canal = ((config_state.output_payload or {}).get('estilo_canal', '')
	                if config_state else '') or DEFAULT_ESTILO_CANAL_CORTO

	# Get topic from P1 Corto
	p1_job = Proceso1CortoJob.query.get(pid)
	tema = p1_job.title if p1_job and hasattr(p1_job, 'title') else 'Short Video'

	# Check for existing prompt station data
	ps_state = Proceso4CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='prompt_station'
	).first()
	existing_prompts = (ps_state.output_payload or {}).get('prompts', {}) if ps_state else {}

	# Build per-scene prompts
	section_prompts: list[dict] = []
	for s in scenes:
		sn = s.get('scene_num', 0)
		existing = existing_prompts.get(str(sn), {})
		# Check media status
		media_count = Proceso4CortoSceneMedia.query.filter_by(
			proceso1_corto_job_id=pid, scene_num=sn
		).count()

		scene_data = {
			'scene_num': sn,
			'section': s.get('section', 'full'),
			'duration': float(s.get('duration', 5.0)),
			'text': s.get('text', ''),
			'visual_type': s.get('visual_type', ''),
			'visual_description': s.get('visual_description', ''),
			'physical_composition': s.get('physical_composition', ''),
			'text_to_video_prompt': existing.get('text_to_video_prompt', ''),
			'text_to_image_prompt': existing.get('text_to_image_prompt', ''),
			'image_to_video_prompt': existing.get('image_to_video_prompt', ''),
			'mediaStatus': 'complete' if media_count > 0 else 'none',
		}
		section_prompts.append(scene_data)

	return jsonify({
		'estilo_canal': estilo_canal,
		'sections': [{
			'section': 'full',
			'sceneCount': len(scenes),
			'status': 'completed' if existing_prompts else 'pending',
			'promptsGenerated': bool(existing_prompts),
			'prompts': section_prompts,
		}],
	})


@proceso4_corto_bp.route('/jobs/<int:pid>/prompt-station/generate', methods=['POST'])
def generate_section_prompts(pid: int):
	get_or_create_job(pid)
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()

	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'Timeline no importado.'}), 404

	scenes = tl.get('scenes', [])

	# Get estilo_canal
	config_state = Proceso4CortoSubprocessState.query.filter_by(
		proceso1_corto_job_id=pid, subprocess_key='config'
	).first()
	estilo_canal = ((config_state.output_payload or {}).get('estilo_canal', '')
	                if config_state else '') or DEFAULT_ESTILO_CANAL_CORTO

	p1_job = Proceso1CortoJob.query.get(pid)
	tema = p1_job.title if p1_job and hasattr(p1_job, 'title') else 'Short Video'

	# Generate prompts for ALL scenes (single "full" section)
	prompts_by_scene: dict[str, dict] = {}
	scene_results = []

	for s in scenes:
		sn = s.get('scene_num', 0)
		dur = float(s.get('duration', 5.0))
		text = s.get('text', '')
		vd = s.get('visual_description', '')
		vt = s.get('visual_type', '')
		pc = s.get('physical_composition', '')

		t2v = build_text_to_video_prompt_corto(
			tema_principal=tema, estilo_canal=estilo_canal,
			narracion_escena=text, concepto_visual_base=vd,
			tipo_visual=vt, duracion_segundos=dur, physical_composition=pc,
		)
		t2i = build_text_to_image_prompt_corto(
			tema_principal=tema, estilo_canal=estilo_canal,
			narracion_escena=text, concepto_visual_base=vd,
			tipo_visual=vt, duracion_segundos=dur, physical_composition=pc,
		)
		i2v = build_image_to_video_prompt_corto(
			tema_principal=tema, estilo_canal=estilo_canal,
			narracion_escena=text, concepto_visual_base=vd,
			tipo_visual=vt, duracion_segundos=dur, physical_composition=pc,
		)

		prompt_data = {
			'text_to_video_prompt': t2v,
			'text_to_image_prompt': t2i,
			'image_to_video_prompt': i2v,
		}
		prompts_by_scene[str(sn)] = prompt_data
		scene_results.append({
			'scene_num': sn,
			'section': 'full',
			'duration': dur,
			'text': text,
			'visual_type': vt,
			'visual_description': vd,
			'physical_composition': pc,
			**prompt_data,
		})

	# Save to subprocess state
	ps_state = get_or_create_subprocess_state(pid, 'prompt_station')
	_save_state(ps_state, {
		'status': 'completed',
		'output': {'prompts': prompts_by_scene},
	})

	return jsonify({
		'section': 'full',
		'sceneCount': len(scenes),
		'scenes': scene_results,
	})


# ---------------------------------------------------------------------------
# Render — Final video at 1080×1920 (vertical 9:16)
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/render', methods=['POST'])
def render_video(pid: int):
	get_or_create_job(pid)

	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()
	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'No timeline imported.'}), 400

	scenes = tl.get('scenes', [])
	if not scenes:
		return jsonify({'error': 'Timeline has no scenes.'}), 400

	narration_path = _get_final_audio_path(pid)
	if not narration_path:
		return jsonify({'error': 'Audio de narración no encontrado (Proceso 2 Corto).'}), 400

	# Collect media assignments
	all_media = Proceso4CortoSceneMedia.query.filter_by(proceso1_corto_job_id=pid).order_by(
		Proceso4CortoSceneMedia.scene_num, Proceso4CortoSceneMedia.clip_index
	).all()
	media_by_scene: dict[int, list[Proceso4CortoSceneMedia]] = {}
	for m in all_media:
		media_by_scene.setdefault(m.scene_num, []).append(m)

	# Mark render state
	render_state = get_or_create_subprocess_state(pid, 'render')
	_save_state(render_state, {'status': 'running', 'output': {'progress': 0}})

	job_dir = get_job_dir(pid)
	work_dir = job_dir / 'output' / 'render_work'
	work_dir.mkdir(parents=True, exist_ok=True)
	output_path = job_dir / 'output' / 'final_video.mp4'

	try:
		# Pre-compute effective durations
		effective_durations: list[float] = []
		for i, scene in enumerate(scenes):
			s_start = float(scene.get('start', 0.0))
			s_dur = float(scene.get('duration', 5.0))
			if i + 1 < len(scenes):
				next_start = float(scenes[i + 1].get('start', 0.0))
				gap = round(next_start - (s_start + s_dur), 4)
				eff = round(s_start + s_dur + max(gap, 0.0) - s_start, 4)
				eff = max(eff, s_dur)
			else:
				eff = s_dur
			effective_durations.append(eff)

		scene_clips: list[str] = []
		render_cursor = 0.0

		for scene_idx, scene in enumerate(scenes):
			sn = scene.get('scene_num', 0)
			eff_duration = effective_durations[scene_idx]
			media_list = media_by_scene.get(sn, [])

			if not media_list:
				clip_path = _build_black_scene(eff_duration, work_dir, sn)
				scene_clips.append(clip_path)
				render_cursor += eff_duration
				continue

			if len(media_list) == 1:
				clip_path = _build_single_clip(media_list[0], eff_duration, work_dir, sn)
			else:
				clip_path = _build_multi_clip(media_list, eff_duration, work_dir, sn)

			scene_clips.append(clip_path)
			render_cursor += eff_duration

		# Pad to audio duration if needed
		narration_dur = _get_video_duration(str(narration_path))
		if narration_dur and narration_dur > render_cursor + 0.5:
			gap = narration_dur - render_cursor
			tail_path = str(work_dir / 'scene_tail.mp4')
			tail_ok = _run_ffmpeg([
				FFMPEG_BIN, '-y',
				'-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r=30',
				'-t', str(gap),
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				tail_path,
			], tag='black tail')
			if tail_ok and _file_ok(tail_path):
				scene_clips.append(tail_path)

		# Filter valid clips
		valid_clips = [cp for cp in scene_clips if _file_ok(cp)]
		if not valid_clips:
			_save_state(render_state, {'status': 'error', 'output': {'error': 'No scene clips generated'}})
			return jsonify({'error': 'No scene clips could be generated.'}), 500

		# Concat all scene clips
		concat_list_path = work_dir / 'concat_scenes.txt'
		with open(concat_list_path, 'w', encoding='utf-8') as f:
			for cp in valid_clips:
				f.write(f"file '{cp}'\n")

		concat_video = str(work_dir / 'all_scenes.mp4')
		concat_ok = _run_ffmpeg([
			FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
			'-i', str(concat_list_path),
			'-c', 'copy', '-an',
			concat_video,
		], timeout=600, tag='concat all scenes')

		if not concat_ok or not _file_ok(concat_video):
			# Fallback: re-encode
			concat_ok = _run_ffmpeg([
				FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
				'-i', str(concat_list_path),
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				concat_video,
			], timeout=600, tag='concat re-encode fallback')

		if not concat_ok or not _file_ok(concat_video):
			_save_state(render_state, {'status': 'error', 'output': {'error': 'Scene concat failed'}})
			return jsonify({'error': 'Scene concat step failed.'}), 500

		# ── SUBTITLE BURN-IN (Montserrat Black) ──────────────────────────
		subtitled_video = concat_video  # default: no subtitles
		try:
			sub_state = Proceso3CortoSubprocessState.query.filter_by(
				proceso1_corto_job_id=pid, subprocess_key='subtitles',
			).first()
			sub_entries = []
			if sub_state and sub_state.status == 'completed':
				sub_entries = (sub_state.output_payload or {}).get('subtitles', [])

			if sub_entries:
				logger.info(f'[P4C] Burning {len(sub_entries)} subtitles with Montserrat Black')

				# Font path (same pattern as P4 largo)
				_raw_font = os.path.join(
					os.path.dirname(os.path.abspath(__file__)),
					'..', '..', '..', '..', 'workspace_aux', 'assets', 'fonts', 'Montserrat-Black.ttf',
				)
				_raw_font = os.path.normpath(_raw_font)

				# Generate ASS subtitle file
				ass_path = work_dir / 'subtitles.ass'
				_generate_ass_file(sub_entries, str(ass_path), _raw_font)

				# FFmpeg drawtext filter — burn subtitles into video
				# NOTE: This FFmpeg build lacks libass (subtitles filter).
				# We use drawtext (libfreetype) instead, chaining one filter per subtitle entry.
				import tempfile

				# Copy font to a temp path without spaces (Windows FFmpeg filter path issue)
				tmp_sub_dir = os.path.join(tempfile.gettempdir(), f'p4c_subs_{pid}')
				os.makedirs(tmp_sub_dir, exist_ok=True)
				tmp_font = os.path.join(tmp_sub_dir, 'Montserrat-Black.ttf')
				if os.path.isfile(_raw_font):
					shutil.copy2(_raw_font, tmp_font)
				font_ff = tmp_font.replace('\\', '/').replace(':', '\\:')

				# Build chained drawtext filters — two per subtitle for word-wrap
				drawtext_filters = []
				for sub in sub_entries:
					start = float(sub.get('start', 0))
					end = float(sub.get('end', 0))
					raw = str(sub.get('text', '')).upper().replace("'", "\u2019")
					enable = f"between(t\\,{start:.3f}\\,{end:.3f})"

					# Common style options
					style = (
						f"fontfile='{font_ff}'"
						f":fontsize=48"
						f":fontcolor=white"
						f":borderw=3"
						f":bordercolor=black"
						f":shadowx=2:shadowy=2:shadowcolor=black@0.5"
						f":x=(w-text_w)/2"
					)

					if len(raw) > 28:
						# Split into 2 lines at word boundary
						words = raw.split()
						l1, l1len, si = [], 0, 0
						for wi, w in enumerate(words):
							nl = l1len + (1 if l1 else 0) + len(w)
							if nl <= 28:
								l1.append(w)
								l1len = nl
								si = wi + 1
							else:
								break
						if not l1:
							l1, si = [words[0]], 1
						l2_words = words[si:]
						l1_text = ' '.join(l1)
						l2_text = ' '.join(l2_words) if l2_words else ''

						if l2_text:
							# Two drawtext filters stacked vertically
							drawtext_filters.append(
								f"drawtext={style}:text='{l1_text}':y=1150:enable='{enable}'"
							)
							drawtext_filters.append(
								f"drawtext={style}:text='{l2_text}':y=1210:enable='{enable}'"
							)
						else:
							drawtext_filters.append(
								f"drawtext={style}:text='{l1_text}':y=1180:enable='{enable}'"
							)
					else:
						# Single line
						drawtext_filters.append(
							f"drawtext={style}:text='{raw}':y=1180:enable='{enable}'"
						)

				vf_chain = ','.join(drawtext_filters)
				subtitled_out = str(work_dir / 'all_scenes_subtitled.mp4')

				sub_ok = _run_ffmpeg([
					FFMPEG_BIN, '-y',
					'-i', concat_video,
					'-vf', vf_chain,
					'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
					subtitled_out,
				], timeout=900, tag='burn subtitles')

				if sub_ok and _file_ok(subtitled_out):
					subtitled_video = subtitled_out
					logger.info(f'[P4C] Subtitles burned successfully')
				else:
					logger.warning('[P4C] Subtitle burn failed, proceeding without subtitles')
		except Exception as e:
			logger.warning(f'[P4C] Subtitle burn error (non-fatal): {e}')

		# Merge audio: narration + optional extra tracks
		extra_tracks = Proceso4CortoAudioTrack.query.filter_by(proceso1_corto_job_id=pid).all()

		if not extra_tracks:
			# Simple: just narration
			cmd_merge = [
				FFMPEG_BIN, '-y',
				'-i', subtitled_video,
				'-i', str(narration_path),
				'-map', '0:v', '-map', '1:a',
				'-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
				'-shortest',
				str(output_path),
			]
		else:
			# Complex mix
			inputs = ['-i', subtitled_video, '-i', str(narration_path)]
			filter_parts = []
			audio_mix_labels = ['[1:a]']
			input_idx = 2

			for i, track in enumerate(extra_tracks):
				if not Path(track.file_path).exists():
					continue
				inputs.extend(['-i', track.file_path])
				idx = input_idx
				delay_ms = int(track.start_time * 1000)
				label = f'extra{i}'
				filter_parts.append(
					f'[{idx}:a]adelay={delay_ms}|{delay_ms},volume={track.volume}[{label}]'
				)
				audio_mix_labels.append(f'[{label}]')
				input_idx += 1

			total_audio = len(audio_mix_labels)
			mix_input = ''.join(audio_mix_labels)
			filter_parts.append(
				f'{mix_input}amix=inputs={total_audio}:duration=longest:dropout_transition=0:normalize=0[aout]'
			)
			cmd_merge = [
				FFMPEG_BIN, '-y',
				*inputs,
				'-filter_complex', ';'.join(filter_parts),
				'-map', '0:v', '-map', '[aout]',
				'-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
				str(output_path),
			]

		result = subprocess.run(cmd_merge, capture_output=True, text=True,
		                        encoding='utf-8', errors='replace', timeout=600)
		if result.returncode != 0:
			logger.error(f"[P4C] FFmpeg merge failed: {result.stderr[-500:]}")
			_save_state(render_state, {
				'status': 'error',
				'output': {'error': f'FFmpeg error: {result.stderr[-300:]}'},
			})
			return jsonify({'error': 'FFmpeg render failed.', 'details': result.stderr[-300:]}), 500

		_save_state(render_state, {
			'status': 'completed',
			'output': {
				'videoPath': str(output_path),
				'scenesRendered': len(valid_clips),
			},
		})

		return jsonify({
			'status': 'completed',
			'videoPath': str(output_path),
			'scenesRendered': len(valid_clips),
		})

	except Exception as e:
		logger.exception(f"[P4C] Render error: {e}")
		_save_state(render_state, {'status': 'error', 'output': {'error': str(e)}})
		return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Download rendered video
# ---------------------------------------------------------------------------

@proceso4_corto_bp.route('/jobs/<int:pid>/download', methods=['GET'])
def download_video(pid: int):
	get_or_create_job(pid)
	output_path = get_job_dir(pid) / 'output' / 'final_video.mp4'
	if not output_path.exists():
		return jsonify({'error': 'Video no renderizado todavía.'}), 404
	return send_file(str(output_path), mimetype='video/mp4', as_attachment=True,
	                 download_name=f'video_corto_{pid}.mp4')
