from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from flask import jsonify, send_file

from aplicacion import db
from aplicacion.models.proceso4 import (
	Proceso4AudioTrack,
	Proceso4ReverbConfig,
	Proceso4SceneMedia,
	Proceso4SectionTrack,
	Proceso4SubprocessState,
)

from .. import proceso4_bp
from ..ffmpeg_setup import FFMPEG_BIN, VIDEO_ENCODER
from ..helpers import (
	get_or_create_job,
	get_or_create_subprocess_state,
	_save_state,
	get_job_dir,
	_get_final_mp3_path,
	_get_video_duration,
	_build_section_title_metadata,
	ensure_scene_media_local_file,
	normalize_audio_track_file_path,
)
from ..render_ffmpeg import (
	_run_ffmpeg,
	_file_ok,
	_build_black_scene,
	_build_single_clip,
	_build_indice_clip,
	_build_pregunta_capciosa_clip,
	_apply_pregunta_text_overlay,
	_build_multi_clip,
	_apply_section_title_overlay,
	_apply_fade_in,
)

logger = logging.getLogger(__name__)


def _prepare_render_work_dir(work_dir: Path) -> None:
	"""Start each render from a clean workspace to avoid stale intermediates."""
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Render — Build final video with FFmpeg
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/render', methods=['POST'])
def render_video(pid: int):
	"""Render the final video from media assignments + narration audio.
	
	This is a synchronous render (blocks until done).
	For production, a job queue (Celery/RQ) would be better.
	"""
	get_or_create_job(pid)

	# Load timeline
	import_state = get_or_create_subprocess_state(pid, 'import_timeline')
	db.session.commit()
	tl = (import_state.output_payload or {}).get('timeline')
	if not tl:
		return jsonify({'error': 'No timeline imported.'}), 400

	scenes = tl.get('scenes', [])
	if not scenes:
		return jsonify({'error': 'Timeline has no scenes.'}), 400

	# Get narration audio
	narration_path = _get_final_mp3_path(pid)
	if not narration_path:
		return jsonify({'error': 'Narration audio (final.mp3) not found in Proceso 2.'}), 400

	# Collect all media assignments
	all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
		Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
	).all()
	media_by_scene: dict[int, list[Proceso4SceneMedia]] = {}
	for m in all_media:
		ensure_scene_media_local_file(m)
		media_by_scene.setdefault(m.scene_num, []).append(m)

	# Allow rendering even if some scenes have no media (they become black screen)
	scenes_without_media = [s for s in scenes if s.get('scene_num') not in media_by_scene]
	if scenes_without_media:
		missing = [s.get('scene_num') for s in scenes_without_media]
		logger.warning(f"[P4] Rendering with missing media scenes (black screen): {missing}")

	# Mark render state
	render_state = get_or_create_subprocess_state(pid, 'render')
	_save_state(render_state, {'status': 'running', 'output': {'progress': 0}})

	# Load auto_indice metadata for animated ÍNDICE rendering
	_ai_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid, subprocess_key='auto_indice'
	).first()
	_ai_out = (_ai_state.output_payload or {}) if _ai_state else {}
	indice_block_start = float(_ai_out.get('start', 0))
	indice_block_total = float(_ai_out.get('total_duration', 0))

	# Track all índice scene nums so we can merge them into one clip at render time
	_indice_scene_nums_ordered: list[int] = list(_ai_out.get('scene_nums', []))
	_indice_scene_nums_set: set[int] = set(_indice_scene_nums_ordered)
	_first_indice_sn: int | None = _indice_scene_nums_ordered[0] if _indice_scene_nums_ordered else None

	job_dir = get_job_dir(pid)
	work_dir = job_dir / 'output' / 'render_work'
	_prepare_render_work_dir(work_dir)
	output_path = job_dir / 'output' / 'final_video.mp4'

	try:
		# Step 1: Create per-scene video clips.
		#
		# The P3 timeline has explicit start times per scene. Natural pauses in the
		# narration audio (Whisper VAD gaps ~0.3-0.8s, plus 2.5s section-boundary
		# silences inserted by P2) create gaps between scene_end and next_scene_start.
		#
		# Strategy: each scene's EFFECTIVE duration = next_scene.start - this_scene.start
		# This absorbs the trailing gap into the clip itself, keeping the video
		# synchronized to the audio with no black frames between content scenes.
		# The last scene uses its own duration (tail-pad handles any audio overshoot).
		#
		# For ÍNDICE scenes: scene_offset_in_indice is computed from scene_start relative
		# to indice_block_start — this is unchanged because start times are still the
		# same P3 values. Only the rendered clip duration changes (slightly extended).

		# Pre-compute effective durations
		effective_durations: list[float] = []
		for i, scene in enumerate(scenes):
			s_start = float(scene.get('start', 0.0))
			s_dur   = float(scene.get('duration', 5.0))
			if i + 1 < len(scenes):
				next_start = float(scenes[i + 1].get('start', 0.0))
				gap = round(next_start - (s_start + s_dur), 4)
				eff = round(s_start + s_dur + max(gap, 0.0) - s_start, 4)  # = next_start - s_start
				eff = max(eff, s_dur)  # never shorter than original
			else:
				eff = s_dur  # last scene: keep original; tail-pad handles audio overshoot
			effective_durations.append(eff)

		# Combined effective duration for all índice scenes (used when merging into one clip)
		_indice_combined_eff_dur: float = 0.0
		if _indice_scene_nums_set:
			for _idx, _sc in enumerate(scenes):
				if _sc.get('scene_num') in _indice_scene_nums_set:
					_indice_combined_eff_dur += effective_durations[_idx]
			logger.info(f"[P4] Índice combined effective duration: {_indice_combined_eff_dur:.3f}s (scenes {_indice_scene_nums_ordered})")

		_section_title_meta = _build_section_title_metadata(pid, scenes, effective_durations)
		scene_clips: list[str] = []
		render_cursor = 0.0  # tracks exact output position (for logging / tail-pad)

		# Fade-in from black: detect section boundaries
		# - Scene index 0 (first scene) → 0.4s fade-in
		# - First scene of each subtema_ section → 0.6s fade-in
		# - No fade-in on cierre
		FADE_IN_FIRST = 0.4   # first scene of the entire video
		FADE_IN_SECTION = 0.6 # first scene after a section boundary (subtemas)

		for scene_idx, scene in enumerate(scenes):
			sn           = scene.get('scene_num', 0)
			scene_start  = float(scene.get('start', 0.0))
			scene_duration = float(scene.get('duration', 5.0))
			eff_duration = effective_durations[scene_idx]
			media_list   = media_by_scene.get(sn, [])

			# Determine if this scene needs a fade-in from black
			cur_section = scene.get('section', '')
			prev_section = scenes[scene_idx - 1].get('section', '') if scene_idx > 0 else ''
			fade_in_dur = 0.0
			if scene_idx == 0:
				fade_in_dur = FADE_IN_FIRST
			elif cur_section != prev_section and cur_section not in ('intro', 'cierre'):
				# Section boundary: fade-in for subtema/parte sections (not intro/cierre)
				fade_in_dur = FADE_IN_SECTION

			absorbed_gap = round(eff_duration - scene_duration, 4)
			if absorbed_gap > 0.05:
				logger.info(
					f"[P4] S{sn}: extending {scene_duration:.3f}s → {eff_duration:.3f}s "
					f"(+{absorbed_gap:.3f}s gap absorbed)"
				)

			section_title_meta = _section_title_meta.get(int(sn or 0))
			if not media_list:
				# No media assigned → black screen of effective duration
				logger.debug(f"[P4] S{sn}: no media → black screen {eff_duration:.3f}s")
				clip_path = _build_black_scene(eff_duration, work_dir, sn)
				if section_title_meta:
					clip_path = _apply_section_title_overlay(
						clip_path,
						eff_duration,
						work_dir,
						sn,
						section_title_meta['title'],
						overlay_elapsed_before=float(section_title_meta.get('elapsed_before', 0.0)),
						overlay_duration=float(section_title_meta.get('overlay_duration', 3.5)),
					)
				if fade_in_dur > 0:
					_apply_fade_in(clip_path, fade_in_dur, work_dir, sn, tag=f'S{sn}')
				scene_clips.append(clip_path)
				render_cursor += eff_duration
				continue

			if len(media_list) == 1:
				clip = media_list[0]
				overlay = clip.text_overlay or {}
				if overlay.get('style') == 'pregunta_capciosa' and overlay.get('lines'):
					pc_text = overlay['lines'][0] if overlay['lines'] else ''
					pc_overlay_start = float(overlay.get('overlay_start', 0.0))
					logger.info(
						f"[P4] S{sn}: PREGUNTA CAPCIOSA clip, "
						f"eff_dur={eff_duration:.3f}s, overlay_start={pc_overlay_start:.3f}s, "
						f"text=\"{pc_text[:50]}…\""
					)
					clip_path = _build_pregunta_capciosa_clip(
						clip, eff_duration, work_dir, sn, pc_text,
						overlay_start=pc_overlay_start,
					)
				elif overlay.get('style') == 'indice' and overlay.get('lines'):
					if _first_indice_sn is not None and sn != _first_indice_sn:
						# Secondary índice scene — the first scene already covers the full block
						# as one combined clip. Advance cursor and skip clip generation.
						render_cursor += eff_duration
						logger.debug(f"[P4] S{sn}: secondary INDICE scene, merged into S{_first_indice_sn}")
						continue
					# First (or only) índice scene: render the full combined block in ONE clip
					_render_dur = _indice_combined_eff_dur if _indice_combined_eff_dur > 0 else eff_duration
					eff_duration = _render_dur  # override so render_cursor advances by the full block
					logger.info(
						f"[P4] S{sn}: INDICE clip (merged block), "
						f"combined_dur={_render_dur:.3f}s"
					)
					clip_path = _build_indice_clip(
						clip, _render_dur, work_dir, sn, overlay['lines'],
						scene_offset_in_indice=0.0,
						total_indice_duration=_render_dur,
					)
				else:
					logger.debug(
						f"[P4] S{sn}: single {clip.media_type} clip, "
						f"eff_dur={eff_duration:.3f}s"
					)
					clip_path = _build_single_clip(clip, eff_duration, work_dir, sn)
				if section_title_meta:
					clip_path = _apply_section_title_overlay(
						clip_path,
						eff_duration,
						work_dir,
						sn,
						section_title_meta['title'],
						overlay_elapsed_before=float(section_title_meta.get('elapsed_before', 0.0)),
						overlay_duration=float(section_title_meta.get('overlay_duration', 3.5)),
					)
				# Apply fade-in from black if needed
				if fade_in_dur > 0:
					_apply_fade_in(clip_path, fade_in_dur, work_dir, sn, tag=f'S{sn}')
				scene_clips.append(clip_path)
			else:
				# Multiple clips: concat/blend to effective duration
				logger.debug(
					f"[P4] S{sn}: multi-clip ({len(media_list)} clips), "
					f"eff_dur={eff_duration:.3f}s"
				)
				clip_path = _build_multi_clip(media_list, eff_duration, work_dir, sn)

				# Check if any clip carries a pregunta_capciosa overlay → apply text on top
				_pc_overlay = None
				for _mc in media_list:
					_mc_ov = _mc.text_overlay or {}
					if _mc_ov.get('style') == 'pregunta_capciosa' and _mc_ov.get('lines'):
						_pc_overlay = _mc_ov
						break
				if _pc_overlay:
					_pc_text = _pc_overlay['lines'][0] if _pc_overlay['lines'] else ''
					_pc_os = float(_pc_overlay.get('overlay_start', 0.0))
					logger.info(
						f"[P4] S{sn}: applying PREGUNTA CAPCIOSA overlay on multi-clip, "
						f"overlay_start={_pc_os:.3f}s, text=\"{_pc_text[:50]}…\""
					)
					clip_path = _apply_pregunta_text_overlay(
						clip_path, eff_duration, work_dir, sn, _pc_text,
						overlay_start=_pc_os,
					)
				if section_title_meta:
					clip_path = _apply_section_title_overlay(
						clip_path,
						eff_duration,
						work_dir,
						sn,
						section_title_meta['title'],
						overlay_elapsed_before=float(section_title_meta.get('elapsed_before', 0.0)),
						overlay_duration=float(section_title_meta.get('overlay_duration', 3.5)),
					)

				# Apply fade-in from black if needed
				if fade_in_dur > 0:
					_apply_fade_in(clip_path, fade_in_dur, work_dir, sn, tag=f'S{sn}')
				scene_clips.append(clip_path)

			render_cursor += eff_duration
			logger.debug(
				f"[P4] S{sn} done → render_cursor={render_cursor:.4f}s "
				f"(tl_start={scene_start:.4f}, eff_dur={eff_duration:.4f})"
			)

		# --- Pad to audio duration: compare against render_cursor (includes all gaps)
		#     rather than just the sum of scene durations. ---
		narration_dur = _get_video_duration(str(narration_path))
		logger.info(
			f"[P4] Render cursor after all scenes: {render_cursor:.3f}s  "
			f"| Narration duration: {narration_dur}s"
		)
		if narration_dur and narration_dur > render_cursor + 0.5:
			gap = narration_dur - render_cursor
			logger.info(f"[P4] Audio is {gap:.1f}s longer than rendered video — appending black tail")
			tail_path = str(work_dir / 'scene_tail.mp4')
			tail_ok = _run_ffmpeg([
				FFMPEG_BIN, '-y',
				'-f', 'lavfi', '-i', 'color=c=black:s=1920x1080:r=30',
				'-t', str(gap),
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				tail_path,
			], tag='black tail')
			if tail_ok and _file_ok(tail_path):
				scene_clips.append(tail_path)

		# Filter out any clips that were not built successfully
		valid_clips = [cp for cp in scene_clips if _file_ok(cp)]
		if not valid_clips:
			_save_state(render_state, {'status': 'error', 'output': {'error': 'No scene clips generated'}})
			return jsonify({'error': 'No scene clips could be generated.'}), 500
		if len(valid_clips) < len(scene_clips):
			logger.warning(f"[P4] {len(scene_clips) - len(valid_clips)} scene clips missing/empty, skipped from concat")

		# Step 2: Concat all scene clips into one video.
		# Use stream-copy (-c copy) to preserve exact per-scene durations and
		# avoid frame-boundary rounding drift that accumulates over many scenes.
		# All sub-clips share identical codec params (same encoder, 1920x1080,
		# 30fps, yuv420p) so -c copy is safe.
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

		# Fallback: if -c copy fails (shouldn't), re-encode as before
		if not concat_ok or not _file_ok(concat_video):
			logger.warning('[P4] Stream-copy concat failed, falling back to re-encode concat')
			concat_ok = _run_ffmpeg([
				FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
				'-i', str(concat_list_path),
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				concat_video,
			], timeout=600, tag='concat all scenes (re-encode fallback)')

		if not concat_ok or not _file_ok(concat_video):
			_save_state(render_state, {'status': 'error', 'output': {'error': 'Scene concat failed'}})
			return jsonify({'error': 'Scene concat step failed. Check server logs.'}), 500

		# Step 3: Merge narration audio + section pistas + reverb + extra tracks
		#
		# Audio sources:
		#   0 = concat video (no audio)
		#   1 = narration (optionally with reverb)
		#   2..N = section pistas (music per section, with fade-in/out)
		#   N+1.. = extra tracks (sfx, etc.)

		extra_tracks = Proceso4AudioTrack.query.filter_by(proceso1_job_id=pid).all()
		normalized_extra_tracks = False
		for track in extra_tracks:
			if normalize_audio_track_file_path(track):
				normalized_extra_tracks = True
		if normalized_extra_tracks:
			db.session.commit()
		section_tracks = Proceso4SectionTrack.query.filter_by(proceso1_job_id=pid).all()
		reverb_config = Proceso4ReverbConfig.query.get(pid)

		# Build section timing map: section_name → (start_time, end_time)
		section_timing: dict[str, tuple[float, float]] = {}
		for sc in scenes:
			sec = sc.get('section', '')
			s_start = float(sc.get('start', 0.0))
			s_dur = float(sc.get('duration', 5.0))
			s_end = s_start + s_dur
			if sec in section_timing:
				existing = section_timing[sec]
				section_timing[sec] = (min(existing[0], s_start), max(existing[1], s_end))
			else:
				section_timing[sec] = (s_start, s_end)

		inputs = ['-i', concat_video, '-i', str(narration_path)]
		filter_parts = []
		audio_mix_labels = []

		# Narration: apply reverb if enabled
		if reverb_config and reverb_config.enabled:
			ig = reverb_config.in_gain
			og = reverb_config.out_gain
			dl = reverb_config.delay_ms
			dc = reverb_config.decay
			filter_parts.append(f'[1:a]aecho={ig}:{og}:{dl}:{dc}[narr]')
			audio_mix_labels.append('[narr]')
		else:
			audio_mix_labels.append('[1:a]')

		# Section pistas
		input_idx = 2
		for st in section_tracks:
			if st.section not in section_timing:
				continue
			if not Path(st.pista_path).exists():
				logger.warning(f'[P4] Section pista file missing: {st.pista_path}')
				continue

			sec_start, sec_end = section_timing[st.section]
			sec_duration = sec_end - sec_start
			delay_ms = int(sec_start * 1000)
			start_offset = max(0.0, float(getattr(st, 'start_offset', 0.0)))

			inputs.extend(['-i', st.pista_path])
			label = f'pista{input_idx}'
			# Trim to section duration, apply delay, volume, and fades
			fade_in_dur = min(st.fade_in, sec_duration / 2)
			fade_out_dur = min(st.fade_out, sec_duration / 2)
			fade_out_start = max(0, sec_duration - fade_out_dur)

			filter_parts.append(
				f'[{input_idx}:a]'
				f'atrim={start_offset}:{start_offset + sec_duration},'
				f'afade=t=in:st=0:d={fade_in_dur},'
				f'afade=t=out:st={fade_out_start}:d={fade_out_dur},'
				f'adelay={delay_ms}|{delay_ms},'
				f'volume={st.volume}'
				f'[{label}]'
			)
			audio_mix_labels.append(f'[{label}]')
			input_idx += 1

		# Extra tracks (sfx, etc.)
		for i, track in enumerate(extra_tracks):
			if not Path(track.file_path).exists():
				logger.warning(f'[P4] Extra track file missing, skipping: {track.file_path}')
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

		total_audio_inputs = len(audio_mix_labels)

		if total_audio_inputs == 1 and not filter_parts:
			# Only narration, no reverb, no section pistas, no extra tracks
			# -shortest: end output when the shorter stream (audio) ends,
			# preventing accumulated frame-rounding from extending video.
			cmd_merge = [
				FFMPEG_BIN, '-y',
				'-i', concat_video,
				'-i', str(narration_path),
				'-map', '0:v', '-map', '1:a',
				'-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
				'-shortest',
				str(output_path),
			]
		else:
			# Complex mix
			# normalize=0 prevents amix from dividing each input's volume by N,
			# which was causing the exported audio to be extremely quiet.
			mix_input = ''.join(audio_mix_labels)
			filter_parts.append(
				f'{mix_input}amix=inputs={total_audio_inputs}:duration=longest:dropout_transition=0:normalize=0[aout]'
			)
			cmd_merge = [
				FFMPEG_BIN, '-y',
				*inputs,
				'-filter_complex', ';'.join(filter_parts),
				'-map', '0:v', '-map', '[aout]',
				'-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
				str(output_path),
			]

		result = subprocess.run(cmd_merge, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
		if result.returncode != 0:
			logger.error(f"[P4] FFmpeg merge failed: {result.stderr[-500:]}")
			_save_state(render_state, {
				'status': 'error',
				'output': {'error': f'FFmpeg error: {result.stderr[-300:]}'},
			})
			return jsonify({'error': 'FFmpeg render failed.', 'details': result.stderr[-300:]}), 500

		# Keep only the final artifact once the render completed successfully.
		shutil.rmtree(work_dir, ignore_errors=True)

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
		logger.exception(f"[P4] Render error: {e}")
		_save_state(render_state, {'status': 'error', 'output': {'error': str(e)}})
		return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------------------------
# Download rendered video
# ---------------------------------------------------------------------------

@proceso4_bp.route('/jobs/<int:pid>/download', methods=['GET'])
def download_video(pid: int):
	"""Download the final rendered video."""
	get_or_create_job(pid)
	output_path = get_job_dir(pid) / 'output' / 'final_video.mp4'
	if not output_path.exists():
		return jsonify({'error': 'Video no renderizado aún.'}), 404
	return send_file(str(output_path), mimetype='video/mp4', as_attachment=True,
					 download_name=f'scienceluxe_video_{pid}.mp4')
