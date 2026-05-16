from __future__ import annotations

import logging
import os
import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path

from aplicacion.models.proceso4 import Proceso4SceneMedia

from .ffmpeg_setup import FFMPEG_BIN, FFPROBE_BIN, VIDEO_ENCODER
from .constants import _SCALE_VF, _IMAGE_MOTION_PRESETS, _IMAGE_MOTION_AUTO_PRESETS, _IMAGE_MOTION_INTENSITIES
from .helpers import _effective_clip_duration

logger = logging.getLogger(__name__)


_SCALE_VF = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2'
_IMAGE_MOTION_PRESETS = {
	'auto',
	'none',
	'zoom_in',
	'zoom_out',
	'pan_left',
	'pan_right',
	'pan_up',
	'pan_down',
	'drift_left_zoom',
	'drift_right_zoom',
}
_IMAGE_MOTION_AUTO_PRESETS = [
	'zoom_in',
	'drift_right_zoom',
	'pan_left',
	'zoom_out',
	'drift_left_zoom',
	'pan_right',
	'pan_up',
	'pan_down',
]
_IMAGE_MOTION_INTENSITIES = {
	'subtle': 0.04,
	'medium': 0.08,
	'strong': 0.12,
}
_IMAGE_MOTION_FPS = 30
_IMAGE_MOTION_OUTPUT_W = 1920
_IMAGE_MOTION_OUTPUT_H = 1080
# Render image motion on a larger internal canvas, then downscale.
# This keeps 1px crop jumps from turning into visible "shakes" on the final 1080p frame.
_IMAGE_MOTION_OVERSAMPLE = 2
_IMAGE_MOTION_INTERNAL_W = _IMAGE_MOTION_OUTPUT_W * _IMAGE_MOTION_OVERSAMPLE
_IMAGE_MOTION_INTERNAL_H = _IMAGE_MOTION_OUTPUT_H * _IMAGE_MOTION_OVERSAMPLE
_IMAGE_MOTION_CACHE_VERSION = 'pillow-subpixel-v1'
_IMAGE_MOTION_CACHE_LOCK = threading.Lock()


def _ensure_clip_path_local(path_str: str) -> bool:
	try:
		from aplicacion.endpoints.clip_library import ensure_clip_library_file_local
		return ensure_clip_library_file_local(path_str)
	except Exception:
		return Path(path_str).exists()


def _normalize_image_motion_preset(value: object) -> str:
	preset = str(value or 'auto').strip().lower()
	return preset if preset in _IMAGE_MOTION_PRESETS else 'auto'


def _normalize_image_motion_intensity(value: object) -> str:
	intensity = str(value or 'medium').strip().lower()
	return intensity if intensity in _IMAGE_MOTION_INTENSITIES else 'medium'


def _resolve_image_motion_preset(clip: Proceso4SceneMedia, scene_num: int) -> str:
	preset = _normalize_image_motion_preset(getattr(clip, 'image_motion_preset', None))
	if preset != 'auto':
		return preset
	idx = (int(scene_num or 0) + int(clip.clip_index or 0)) % len(_IMAGE_MOTION_AUTO_PRESETS)
	return _IMAGE_MOTION_AUTO_PRESETS[idx]


def _build_static_image_clip(
	clip: Proceso4SceneMedia,
	duration: float,
	out: str,
	scene_num: int,
	tag: str,
) -> bool:
	if not _ensure_clip_path_local(clip.file_path):
		return False
	return _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-loop', '1', '-i', clip.file_path,
		'-t', str(duration),
		'-vf', _SCALE_VF,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=tag or f'S{scene_num} image static')


def _smoothstep(t: float) -> float:
	t = max(0.0, min(1.0, t))
	return t * t * (3.0 - 2.0 * t)


def _lerp(start: float, end: float, t: float) -> float:
	return start + (end - start) * t


def _image_motion_keyframes(preset: str, intensity_name: str) -> tuple[float, float, float, float, float, float]:
	amount = _IMAGE_MOTION_INTENSITIES[_normalize_image_motion_intensity(intensity_name)]
	max_zoom = 1.0 + amount
	start_zoom = max_zoom
	end_zoom = max_zoom
	x_from = 0.5
	x_to = 0.5
	y_from = 0.5
	y_to = 0.5

	if preset == 'zoom_in':
		start_zoom = 1.0
		end_zoom = max_zoom
	elif preset == 'zoom_out':
		start_zoom = max_zoom
		end_zoom = 1.0
	elif preset == 'pan_left':
		x_from = 1.0
		x_to = 0.0
	elif preset == 'pan_right':
		x_from = 0.0
		x_to = 1.0
	elif preset == 'pan_up':
		y_from = 1.0
		y_to = 0.0
	elif preset == 'pan_down':
		y_from = 0.0
		y_to = 1.0
	elif preset == 'drift_left_zoom':
		start_zoom = 1.0
		end_zoom = max_zoom
		x_from = 1.0
		x_to = 0.0
	elif preset == 'drift_right_zoom':
		start_zoom = 1.0
		end_zoom = max_zoom
		x_from = 0.0
		x_to = 1.0

	return start_zoom, end_zoom, x_from, x_to, y_from, y_to


def _image_motion_cache_root(out: str) -> Path:
	"""Return a job-level cache dir shared by final render and scene previews."""
	out_parent = Path(out).resolve().parent
	if out_parent.name == 'render_work':
		return out_parent.parent / 'image_motion_cache'
	if out_parent.parent.name == 'scene_previews':
		return out_parent.parent.parent / 'image_motion_cache'
	return out_parent / '_image_motion_cache'


def _image_motion_cache_path(
	image_path: str,
	duration: float,
	preset: str,
	intensity_name: str,
	out: str,
	progress_start: float,
	progress_end: float,
) -> Path | None:
	src = Path(image_path)
	try:
		stat = src.stat()
	except OSError:
		return None
	payload = {
		'version': _IMAGE_MOTION_CACHE_VERSION,
		'image_path': str(src.resolve()),
		'image_mtime': stat.st_mtime,
		'image_size': stat.st_size,
		'duration': round(float(duration or 0.0), 4),
		'preset': _normalize_image_motion_preset(preset),
		'intensity': _normalize_image_motion_intensity(intensity_name),
		'progress_start': round(float(progress_start), 6),
		'progress_end': round(float(progress_end), 6),
		'fps': _IMAGE_MOTION_FPS,
		'width': _IMAGE_MOTION_OUTPUT_W,
		'height': _IMAGE_MOTION_OUTPUT_H,
	}
	digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()
	return _image_motion_cache_root(out) / f'{digest}.mp4'


def _render_image_motion_clip(
	image_path: str,
	duration: float,
	out: str,
	preset: str,
	intensity_name: str,
	tag: str = '',
	progress_start: float = 0.0,
	progress_end: float = 1.0,
) -> bool:
	"""Render still-image motion with real sub-pixel sampling.

	FFmpeg's zoompan/crop path rounds crop coordinates to whole pixels. For slow
	zooms that shows up as visible jitter, so still-image motion is generated as
	raw RGB frames with Pillow float crop boxes and FFmpeg only encodes the stream.
	"""
	try:
		from PIL import Image, ImageOps
	except Exception as exc:
		logger.warning(f"[P4] Pillow unavailable for image motion ({exc}); falling back to FFmpeg static image")
		return False

	duration = max(float(duration or 0.0), 0.1)
	frame_count = max(int(round(duration * _IMAGE_MOTION_FPS)), 1)
	out_w = _IMAGE_MOTION_OUTPUT_W
	out_h = _IMAGE_MOTION_OUTPUT_H
	resample = Image.Resampling.BICUBIC
	cache_path = _image_motion_cache_path(
		image_path,
		duration,
		preset,
		intensity_name,
		out,
		progress_start,
		progress_end,
	)
	if cache_path and _file_ok(str(cache_path)):
		try:
			Path(out).parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(cache_path, out)
			logger.info(f"[P4]{' ' + tag if tag else ''} image motion cache hit")
			return _file_ok(out)
		except OSError as exc:
			logger.warning(f"[P4]{' ' + tag if tag else ''} image motion cache read failed: {exc}")

	try:
		if not _ensure_clip_path_local(image_path):
			return False
		Path(out).parent.mkdir(parents=True, exist_ok=True)
		src = ImageOps.exif_transpose(Image.open(image_path)).convert('RGB')
		src_w, src_h = src.size
		if src_w <= 0 or src_h <= 0:
			return False

		start_zoom, end_zoom, x_from, x_to, y_from, y_to = _image_motion_keyframes(preset, intensity_name)
		base_scale = max(out_w / src_w, out_h / src_h)
		progress_span = progress_end - progress_start

		cmd = [
			FFMPEG_BIN, '-y',
			'-loglevel', 'error',
			'-f', 'rawvideo',
			'-pix_fmt', 'rgb24',
			'-s', f'{out_w}x{out_h}',
			'-r', str(_IMAGE_MOTION_FPS),
			'-i', '-',
			'-frames:v', str(frame_count),
			'-c:v', VIDEO_ENCODER,
			'-pix_fmt', 'yuv420p',
			'-r', str(_IMAGE_MOTION_FPS),
			'-an',
			out,
		]
		proc = subprocess.Popen(
			cmd,
			stdin=subprocess.PIPE,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
		)
		assert proc.stdin is not None

		for frame_idx in range(frame_count):
			local_t = frame_idx / max(frame_count - 1, 1)
			motion_t = _smoothstep(progress_start + progress_span * local_t)
			zoom = _lerp(start_zoom, end_zoom, motion_t)
			x_pct = _lerp(x_from, x_to, motion_t)
			y_pct = _lerp(y_from, y_to, motion_t)

			scale = base_scale * zoom
			view_w = min(src_w, out_w / scale)
			view_h = min(src_h, out_h / scale)
			left = max(0.0, (src_w - view_w) * x_pct)
			top = max(0.0, (src_h - view_h) * y_pct)
			box = (left, top, left + view_w, top + view_h)
			frame = src.transform((out_w, out_h), Image.Transform.EXTENT, box, resample=resample)
			proc.stdin.write(frame.tobytes())

		proc.stdin.close()
		stderr = proc.stderr.read().decode('utf-8', errors='replace') if proc.stderr else ''
		rc = proc.wait(timeout=60)
		if rc != 0:
			logger.error(f"[P4]{' ' + tag if tag else ''} Pillow motion encode failed (rc={rc}): {stderr[-400:]}")
			return False
		ok = _file_ok(out)
		if ok and cache_path:
			try:
				cache_path.parent.mkdir(parents=True, exist_ok=True)
				with _IMAGE_MOTION_CACHE_LOCK:
					if not _file_ok(str(cache_path)):
						shutil.copy2(out, cache_path)
			except OSError as exc:
				logger.warning(f"[P4]{' ' + tag if tag else ''} image motion cache write failed: {exc}")
		return ok
	except Exception as exc:
		logger.exception(f"[P4]{' ' + tag if tag else ''} Pillow image motion crashed: {exc}")
		try:
			if 'proc' in locals() and proc.poll() is None:
				proc.kill()
		except Exception:
			pass
		return False


def _build_image_motion_clip(
	clip: Proceso4SceneMedia,
	duration: float,
	out: str,
	scene_num: int,
	tag: str = '',
) -> bool:
	"""Render an image clip with optional Ken Burns motion.

	Only image clips call this helper. Videos keep their existing path.
	"""
	preset = _normalize_image_motion_preset(getattr(clip, 'image_motion_preset', None))
	intensity = _normalize_image_motion_intensity(getattr(clip, 'image_motion_intensity', None))
	if preset == 'none':
		return _build_static_image_clip(clip, duration, out, scene_num, tag or f'S{scene_num} image none')

	resolved = _resolve_image_motion_preset(clip, scene_num)
	ok = _render_image_motion_clip(
		clip.file_path,
		duration,
		out,
		resolved,
		intensity,
		tag=tag or f'S{scene_num} image motion {resolved}/{intensity}',
	)

	if ok and _file_ok(out):
		return True

	logger.warning(
		f"[P4] S{scene_num}: image motion failed "
		f"({resolved}/{intensity}), falling back to static image"
	)
	return _build_static_image_clip(clip, duration, out, scene_num, f'S{scene_num} image static fallback')


def _run_ffmpeg(cmd: list, timeout: int = 180, tag: str = '') -> bool:
	"""Run an FFmpeg command; returns True on success, logs stderr on failure."""
	result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
	if result.returncode != 0:
		logger.error(f"[P4]{' ' + tag if tag else ''} FFmpeg failed (rc={result.returncode}): {result.stderr[-400:]}")
		return False
	return True


def _file_ok(path: str) -> bool:
	"""Return True if path exists and has non-zero size."""
	p = Path(path)
	return p.exists() and p.stat().st_size > 0


def _build_black_scene(scene_duration: float, work_dir: Path, scene_num: int) -> str:
	"""Build a black screen video segment of exact duration (no audio)."""
	out = str(work_dir / f'scene_{scene_num}.mp4')
	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-f', 'lavfi', '-i', f'color=c=black:s=1920x1080:r=30',
		'-t', str(scene_duration),
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'black S{scene_num}')
	if not ok or not _file_ok(out):
		logger.error(f"[P4] Black scene fallback also failed for scene {scene_num}")
	return out


def _apply_fade_in(clip_path: str, fade_duration: float, work_dir: Path,
					scene_num: int, tag: str = '') -> str:
	"""Apply a video fade-in from black to the beginning of a clip.

	Re-encodes the clip with an FFmpeg `fade=t=in` filter.
	Returns the (possibly updated) clip_path.
	"""
	if fade_duration <= 0:
		return clip_path
	faded_path = str(work_dir / f'scene_{scene_num}_fadein.mp4')
	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-i', clip_path,
		'-vf', f'fade=t=in:st=0:d={fade_duration:.3f}',
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		faded_path,
	], tag=f'{tag} fade-in {fade_duration:.1f}s')
	if ok and _file_ok(faded_path):
		import shutil
		shutil.move(faded_path, clip_path)
		logger.info(f"[P4]{' ' + tag if tag else ''} Applied {fade_duration:.1f}s fade-in from black")
	else:
		logger.warning(f"[P4]{' ' + tag if tag else ''} Fade-in failed — using clip without fade")
	return clip_path


def _get_clip_duration(path: str) -> float:
	"""Probe the duration of a video file in seconds. Returns 0.0 on failure."""
	try:
		result = subprocess.run(
			[FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
			 '-of', 'default=noprint_wrappers=1:nokey=1', path],
			capture_output=True, text=True, timeout=30,
		)
		return float(result.stdout.strip())
	except Exception:
		return 0.0


def _pad_to_duration(clip_path: str, target_duration: float, work_dir: Path,
					  scene_num: int, tag: str = '') -> str:
	"""Ensure a clip is EXACTLY target_duration seconds long (within 1-frame tolerance).

	Handles both undershoot (pad) and overshoot (trim):

	Overshoot (clip too long):
	  - Trim to exact target_duration with stream-copy (-c copy) — no re-encode.
	    This prevents micro-excesses from accumulating across many scenes.

	Undershoot strategies by shortfall size:
	  - ≤ 1.0s : Slow the clip down slightly with setpts so it fills the target
	              duration. E.g. 8.8s → 9.28s = 1.054× slowdown (barely visible).
	  - > 1.0s : Fade the clip to black over the last 0.5s, then fill the rest
	              with black frames. This happens at section boundaries where
	              there's narration silence anyway, so black is natural.

	Returns the (possibly updated) clip_path.
	"""
	actual = _get_clip_duration(clip_path)
	if actual <= 0:
		return clip_path

	# --- OVERSHOOT: trim clip to exact target duration ---
	if actual > target_duration + 0.04:  # more than 1 frame too long
		trimmed_path = str(work_dir / f'scene_{scene_num}_trimmed.mp4')
		logger.info(
			f"[P4]{' ' + tag if tag else ''} Clip {actual:.3f}s > target {target_duration:.3f}s "
			f"(overshoot +{actual - target_duration:.3f}s) — trimming"
		)
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-i', clip_path,
			'-t', str(target_duration),
			'-c', 'copy', '-an',
			trimmed_path,
		], tag=f'{tag} trim overshoot')
		if ok and _file_ok(trimmed_path):
			import shutil
			shutil.move(trimmed_path, clip_path)
			logger.info(f"[P4]{' ' + tag if tag else ''} Trimmed to {_get_clip_duration(clip_path):.3f}s")
		else:
			logger.warning(f"[P4]{' ' + tag if tag else ''} Trim failed — proceeding with {actual:.3f}s clip")
		return clip_path

	# Within tolerance (±1 frame) — no action needed
	if actual >= target_duration - 0.04:
		return clip_path

	shortfall = target_duration - actual
	padded_path = str(work_dir / f'scene_{scene_num}_padded.mp4')
	ok = False

	if shortfall <= 1.0 and actual > 0.5:
		# ── Small gap: slow down the video imperceptibly ──
		# PTS multiplier > 1.0 slows video.  E.g. 9.28/8.8 = 1.0545
		pts_factor = target_duration / actual
		logger.info(
			f"[P4]{' ' + tag if tag else ''} Clip {actual:.3f}s → {target_duration:.3f}s "
			f"(slowing {pts_factor:.4f}× to fill +{shortfall:.3f}s gap)"
		)
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-i', clip_path,
			'-vf', f'{_SCALE_VF},setpts={pts_factor:.6f}*PTS',
			'-r', '30',
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-an',
			padded_path,
		], tag=f'{tag} slowmo ×{pts_factor:.3f}')
	else:
		# ── Large gap (section boundary): fade to black + black padding ──
		# Fade the last 0.5s of original clip to black, then append black frames
		fade_dur = min(0.5, actual * 0.3)  # fade at most 30% of clip or 0.5s
		fade_start = max(0, actual - fade_dur)
		logger.info(
			f"[P4]{' ' + tag if tag else ''} Clip {actual:.3f}s → {target_duration:.3f}s "
			f"(fade-to-black at {fade_start:.2f}s + {shortfall:.3f}s black padding)"
		)
		# Build: original with fade-out, then concat with black segment
		faded_path = str(work_dir / f'scene_{scene_num}_faded.mp4')
		ok_fade = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-i', clip_path,
			'-vf', f'fade=t=out:st={fade_start:.4f}:d={fade_dur:.4f}',
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			faded_path,
		], tag=f'{tag} fade-out')

		black_path = str(work_dir / f'scene_{scene_num}_black_tail.mp4')
		ok_black = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-f', 'lavfi', '-i', 'color=c=black:s=1920x1080:r=30',
			'-t', str(shortfall),
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			black_path,
		], tag=f'{tag} black tail {shortfall:.2f}s')

		if ok_fade and _file_ok(faded_path) and ok_black and _file_ok(black_path):
			# Concat faded clip + black tail
			pad_concat = work_dir / f'scene_{scene_num}_pad_concat.txt'
			with open(pad_concat, 'w', encoding='utf-8') as fh:
				fh.write(f"file '{faded_path}'\n")
				fh.write(f"file '{black_path}'\n")
			ok = _run_ffmpeg([
				FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
				'-i', str(pad_concat),
				'-c', 'copy', '-an',
				padded_path,
			], tag=f'{tag} concat fade+black')

	if ok and _file_ok(padded_path):
		import shutil
		shutil.move(padded_path, clip_path)
		logger.info(f"[P4]{' ' + tag if tag else ''} Padded clip duration: {_get_clip_duration(clip_path):.3f}s")
	else:
		logger.warning(f"[P4]{' ' + tag if tag else ''} Padding failed — clip will be short ({actual:.3f}s < {target_duration:.3f}s)")

	return clip_path


def _encode_segment(src_or_lavfi: str, is_lavfi: bool, out: str,
					 t: float, ss: float = 0.0, tag: str = '') -> bool:
	"""Encode a single video segment to 1920x1080 H.264 with no audio."""
	if not is_lavfi and not _ensure_clip_path_local(src_or_lavfi):
		return False
	input_args = (['-f', 'lavfi', '-i', src_or_lavfi] if is_lavfi
				  else (['-ss', str(ss)] if ss > 0 else []) + ['-i', src_or_lavfi])
	return _run_ffmpeg([
		FFMPEG_BIN, '-y',
		*input_args,
		'-t', str(t),
		'-vf', _SCALE_VF,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=tag)


def _build_single_clip(clip: Proceso4SceneMedia, scene_duration: float, work_dir: Path, scene_num: int) -> str:
	"""Build a single-clip scene to exact duration. Falls back to black on failure.

	If the video clip is shorter than scene_duration (e.g. because effective_duration
	absorbed inter-section silence gaps), the clip is padded with a freeze-frame of
	the last frame so that the concat produces the exact total duration needed to
	stay in sync with the narration audio and SRT timestamps.
	"""
	out = str(work_dir / f'scene_{scene_num}.mp4')

	if clip.media_type == 'image':
		ok = _build_image_motion_clip(clip, scene_duration, out, scene_num, tag=f'S{scene_num} image')
	else:
		if not _ensure_clip_path_local(clip.file_path):
			ok = False
		else:
			spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
			trim_start = clip.trim_start or 0.0
			trim_end = clip.trim_end if clip.trim_end else (trim_start + scene_duration * spd)
			raw_dur = trim_end - trim_start  # source frames to read (before speed)
			# After speed, the clip contributes raw_dur/spd seconds of output
			clip_out_dur = min(raw_dur / spd, scene_duration)
			if abs(spd - 1.0) > 0.01:
				pts_factor = 1.0 / spd  # 2x speed → 0.5*PTS (faster)
				vf = f'{_SCALE_VF},setpts={pts_factor:.6f}*PTS'
				logger.info(f"[P4] S{scene_num}: speed={spd}x setpts={pts_factor:.4f}*PTS raw={raw_dur:.2f}s eff={clip_out_dur:.2f}s")
			else:
				vf = _SCALE_VF
			# Limit input reading to raw_dur; hard-cap OUTPUT to scene_duration
			# to prevent frame-rounding overshoot from accumulating across scenes.
			input_args = (['-ss', str(trim_start)] if trim_start > 0 else []) + ['-i', clip.file_path]
			cmd = [
				FFMPEG_BIN, '-y',
				*input_args,
				'-t', str(raw_dur),
				'-vf', vf,
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			]
			# If speed changes the output duration, add hard output cap
			if abs(spd - 1.0) > 0.01:
				cmd.extend(['-t', str(scene_duration)])
			cmd.append(out)
			ok = _run_ffmpeg(cmd, tag=f'S{scene_num} video spd={spd}x')

	if not ok or not _file_ok(out):
		logger.warning(f"[P4] Single clip encode failed for scene {scene_num}, using black screen")
		_build_black_scene(scene_duration, work_dir, scene_num)
		return out

	# --- POST-ENCODE DURATION CHECK ---
	# Ensures exact duration: pads short clips AND trims overshoots.
	_pad_to_duration(out, scene_duration, work_dir, scene_num, tag=f'S{scene_num}')

	return out


def _build_indice_clip(
	clip: Proceso4SceneMedia,
	scene_duration: float,
	work_dir: Path,
	scene_num: int,
	subtemas: list[str],
	scene_offset_in_indice: float = 0.0,
	total_indice_duration: float = 0.0,
) -> str:
	"""Build an ÍNDICE scene clip: background image with slow Ken Burns zoom-in
	+ animated per-subtema drawtext.

	Each subtema fades in individually at the proportional time within the ÍNDICE block.
	For example, 4 subtemas over 25s → subtema 0 at 0s, subtema 1 at 6.25s, etc.

	The background image has a continuous slow zoom-in (100% → 108%) across the
	entire índice block.  scene_offset_in_indice is used to start the zoom at
	the correct level so consecutive scenes produce a seamless zoom.

	scene_offset_in_indice : seconds from the start of the full ÍNDICE block to this scene.
	total_indice_duration   : total duration (seconds) of the full ÍNDICE block.

	Falls back to static overlay → plain image → black screen on failure.
	"""
	out = str(work_dir / f'scene_{scene_num}.mp4')
	if not _ensure_clip_path_local(clip.file_path):
		_build_black_scene(scene_duration, work_dir, scene_num)
		return out

	# Font path — Montserrat Black (project asset, portable across machines)
	_raw_font = os.path.join(
		os.path.dirname(os.path.abspath(__file__)),
		'..', '..', '..', '..', 'workspace_aux', 'assets', 'fonts', 'Montserrat-Black.ttf'
	)
	_raw_font = os.path.normpath(_raw_font)
	# FFmpeg drawtext requires forward slashes and colon-escaped drive letter on Windows
	font_path_ff = _raw_font.replace('\\', '/').replace(':', '\\:')

	def _ff_escape(s: str) -> str:
		"""Escape a string for use inside an ffmpeg drawtext text= option."""
		return (s
			.replace('\\', '\\\\')
			.replace("'",  "\\'")
			.replace(':',  '\\:')
			.replace(',',  '\\,')
			.replace('%',  '\\%')
			.replace('\n', ' '))

	# Subtitle fade-out: all subtemas fade to transparent in the last 1.5s of the block
	FADE_OUT_DUR = 1.5
	fade_out_start = max(0.0, scene_duration - FADE_OUT_DUR)

	# Build the animated background with the shared sub-pixel image-motion engine.
	total_indice_duration = total_indice_duration or scene_duration
	progress_start = max(0.0, scene_offset_in_indice / max(total_indice_duration, 0.1))
	progress_end = max(
		progress_start,
		min(1.0, (scene_offset_in_indice + scene_duration) / max(total_indice_duration, 0.1)),
	)
	motion_base = str(work_dir / f'scene_{scene_num}_indice_motion_base.mp4')
	bg_ok = _render_image_motion_clip(
		clip.file_path,
		scene_duration,
		motion_base,
		'zoom_in',
		'medium',
		tag=f'S{scene_num} indice smooth motion',
		progress_start=progress_start,
		progress_end=progress_end,
	)
	if not bg_ok or not _file_ok(motion_base):
		logger.warning(f"[P4] Indice smooth motion failed for scene {scene_num}, trying static background")
		bg_ok = _build_static_image_clip(clip, scene_duration, motion_base, scene_num, f'S{scene_num} indice static bg')
	if not bg_ok or not _file_ok(motion_base):
		logger.warning(f"[P4] All indice background methods failed for scene {scene_num}, using black screen")
		_build_black_scene(scene_duration, work_dir, scene_num)
		return out

	n = len(subtemas)
	# Build per-subtema drawtext filter chain
	drawtext_parts: list[str] = []

	if n > 0 and total_indice_duration > 0:
		slot_size   = total_indice_duration / n
		line_height = 62  # px between subtema lines (fontsize 36 Montserrat Black + padding)
		# Anchor the list in the lower quarter of the frame
		y_base = max(60, 1080 - n * line_height - 100)

		for i, subtema in enumerate(subtemas):
			# Global appear time within the ÍNDICE block (staggered per subtema)
			appear_global = i * slot_size
			# Local appear time within THIS clip
			local_appear  = appear_global - scene_offset_in_indice

			# Skip subtemas that haven't appeared AND won't appear in this clip
			if local_appear >= scene_duration + 0.1:
				continue

			y_pos = y_base + i * line_height
			text_file = str(work_dir / f'scene_{scene_num}_indice_subtema_{i}.txt')
			visual_text = (
				str(subtema)
				.replace('—', '-')
				.replace('–', '-')
				.replace('“', '"')
				.replace('”', '"')
				.replace('‘', "'")
				.replace('’', "'")
				.replace(' ? ', ' - ')
			)
			with open(text_file, 'w', encoding='utf-8') as _tf:
				_tf.write(f'- {visual_text}'.replace('%', '%%'))
			text_file_ff = text_file.replace('\\', '/').replace(':', '\\:')

			fade_dur = 0.7
			if local_appear <= 0:
				# Already visible before this clip starts → full opacity, then fade out at end
				alpha_expr = (
					f"if(lt(t,{fade_out_start:.3f}),"
					f"1,"
					f"max(0,1-(t-{fade_out_start:.3f})/{FADE_OUT_DUR:.1f}))"
				)
			else:
				# Fade in during this clip, then fade out at end
				alpha_expr = (
					f"if(lt(t,{local_appear:.3f}),"
					f"0,"
					f"if(lt(t,{fade_out_start:.3f}),"
					f"min(1,(t-{local_appear:.3f})/{fade_dur:.1f}),"
					f"max(0,1-(t-{fade_out_start:.3f})/{FADE_OUT_DUR:.1f})))"
				)

			alpha_expr = alpha_expr.replace(',', r'\,')
			drawtext_parts.append(
				f"drawtext=fontfile='{font_path_ff}'"
				f":textfile='{text_file_ff}'"
				f":fontcolor=white"
				f":fontsize=36"
				f":box=1:boxcolor=black@0.60:boxborderw=16"
				f":x=80"
				f":y={y_pos}"
				f":alpha='{alpha_expr}'"
			)

	# ── Assemble text overlay on top of the already-rendered smooth background ──
	if drawtext_parts:
		vf = ','.join(drawtext_parts)
	else:
		# No timed drawtext possible — fall through to static bullet list
		n_subtemas = len(subtemas)
		if n_subtemas > 0:
			bullet_lines = [_ff_escape(f'• {t}') for t in subtemas]
			text_str = r'\n'.join(bullet_lines)
			vf = (
				f"drawtext=fontfile='{font_path_ff}'"
				+ f":text='{text_str}'"
				+ ":fontcolor=white:fontsize=36:line_spacing=12"
				+ ":box=1:boxcolor=black@0.60:boxborderw=16"
				+ ":x=80:y=(h-text_h-80)"
			)
		else:
			shutil.move(motion_base, out)
			return out

	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-i', motion_base,
		'-t', str(scene_duration),
		'-vf', vf,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'S{scene_num} indice smooth text')

	if not ok or not _file_ok(out):
		logger.warning(f"[P4] Indice text overlay failed for scene {scene_num}, using smooth background only")
		try:
			shutil.move(motion_base, out)
		except OSError:
			_build_black_scene(scene_duration, work_dir, scene_num)

	return out


def _build_pregunta_capciosa_clip(
	clip: Proceso4SceneMedia,
	scene_duration: float,
	work_dir: Path,
	scene_num: int,
	text: str,
	overlay_start: float = 0.0,
) -> str:
	"""Build a "pregunta capciosa" scene with centred text fade-in.

	Two-pass approach for maximum reliability:
	  Pass 1 — build the standard 1920×1080 clip via _build_single_clip (known good).
	  Pass 2 — apply centred drawtext with fade-in starting at *overlay_start*.

	Falls back to the plain Pass-1 clip if Pass 2 fails.
	"""
	out = str(work_dir / f'scene_{scene_num}.mp4')

	# ── Pass 1: build base clip with the standard pipeline ──────────────
	base_clip = _build_single_clip(clip, scene_duration, work_dir, scene_num)
	# _build_single_clip writes to `out`; rename so Pass 2 can read it
	base_path = str(work_dir / f'scene_{scene_num}_pcbase.mp4')
	try:
		if os.path.exists(base_path):
			os.remove(base_path)
		os.rename(base_clip, base_path)
	except OSError as e:
		logger.warning(f"[P4] S{scene_num}: rename failed ({e}), skipping pregunta overlay")
		return base_clip

	# ── Font path (same as _build_indice_clip) ──────────────────────────
	_raw_font = os.path.join(
		os.path.dirname(os.path.abspath(__file__)),
		'..', '..', '..', '..', 'workspace_aux', 'assets', 'fonts', 'Montserrat-Black.ttf'
	)
	_raw_font = os.path.normpath(_raw_font)
	font_path_ff = _raw_font.replace('\\', '/').replace(':', '\\:')

	# ── Normalise: collapse any embedded newlines / literal \n sequences ──
	norm_text = text.replace('\\n', ' ').replace('\n', ' ')
	norm_text = ' '.join(norm_text.split())

	# ── Wrap text into ≤38-char lines (~60 % screen width) ──────────────
	max_chars_per_line = 48
	words = norm_text.split()
	lines: list[str] = []
	current_line = ''
	for w in words:
		test = (current_line + ' ' + w).strip()
		if len(test) <= max_chars_per_line:
			current_line = test
		else:
			if current_line:
				lines.append(current_line)
			current_line = w
	if current_line:
		lines.append(current_line)

	# Write word-wrapped text to a temp file with real newlines.
	# Using textfile= avoids all FFmpeg filter-graph escaping issues with \n.
	wrapped = '\n'.join(lines) if lines else norm_text
	wrapped = wrapped.replace('%', '%%')  # escape drawtext % expansion
	text_file = str(work_dir / f'scene_{scene_num}_pctext.txt')
	with open(text_file, 'w', encoding='utf-8') as _tf:
		_tf.write(wrapped)
	text_file_ff = text_file.replace('\\', '/').replace(':', '\\:')

	dur = max(scene_duration, 0.1)

	_os = max(overlay_start, 0.0)
	_fade_end = _os + 0.5
	alpha_expr = (
		f"if(lt(t,{_os:.3f}),0,"
		f"if(lt(t,{_fade_end:.3f}),(t-{_os:.3f})/0.5,1))"
	)
	alpha_expr = alpha_expr.replace(',', r'\,')

	drawtext = (
		f"drawtext=fontfile='{font_path_ff}'"
		f":textfile='{text_file_ff}'"
		f":fontcolor=white:fontsize=52"
		f":shadowcolor=black@0.7:shadowx=3:shadowy=3"
		f":x=(w-text_w)/2:y=(h-text_h)/2"
		f":alpha='{alpha_expr}'"
	)

	vf = drawtext

	logger.info(f"[P4] S{scene_num} pregunta-capciosa overlay_start={_os:.3f}s vf={vf[:200]}…")

	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-i', base_path,
		'-t', str(dur),
		'-vf', vf,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'S{scene_num} pregunta-capciosa')

	if not ok or not _file_ok(out):
		logger.warning(
			f"[P4] Pregunta capciosa Pass 2 failed for scene {scene_num}, "
			f"using base clip without overlay"
		)
		os.rename(base_path, out)
		return out

	# Clean up temp base
	try:
		os.remove(base_path)
	except OSError:
		pass

	return out


def _apply_pregunta_text_overlay(
	base_clip_path: str,
	scene_duration: float,
	work_dir: Path,
	scene_num: int,
	text: str,
	overlay_start: float = 0.0,
) -> str:
	"""Apply pregunta capciosa drawtext overlay on an already-built clip (e.g. multi-clip).

	Reads base_clip_path → writes the drawtext result to scene_{scene_num}.mp4.
	Text appears at *overlay_start* seconds with a 0.5 s fade-in.
	Falls back to the original clip if ffmpeg fails.
	"""
	out = str(work_dir / f'scene_{scene_num}.mp4')
	temp_base = str(work_dir / f'scene_{scene_num}_pcmulti.mp4')
	try:
		if os.path.exists(temp_base):
			os.remove(temp_base)
		os.rename(base_clip_path, temp_base)
	except OSError as e:
		logger.warning(f"[P4] S{scene_num}: rename for PC overlay failed ({e})")
		return base_clip_path

	# Font
	_raw_font = os.path.join(
		os.path.dirname(os.path.abspath(__file__)),
		'..', '..', '..', '..', 'workspace_aux', 'assets', 'fonts', 'Montserrat-Black.ttf'
	)
	_raw_font = os.path.normpath(_raw_font)
	font_path_ff = _raw_font.replace('\\', '/').replace(':', '\\:')

	# Normalise: collapse any embedded newlines / literal \n sequences
	norm_text = text.replace('\\n', ' ').replace('\n', ' ')
	norm_text = ' '.join(norm_text.split())

	# Word-wrap
	max_cpl = 38
	words = norm_text.split()
	lines: list[str] = []
	cur = ''
	for w in words:
		test = (cur + ' ' + w).strip()
		if len(test) <= max_cpl:
			cur = test
		else:
			if cur:
				lines.append(cur)
			cur = w
	if cur:
		lines.append(cur)

	# Write word-wrapped text to a temp file with real newlines.
	# Using textfile= avoids all FFmpeg filter-graph escaping issues with \n.
	wrapped = '\n'.join(lines) if lines else norm_text
	wrapped = wrapped.replace('%', '%%')  # escape drawtext % expansion
	text_file = str(work_dir / f'scene_{scene_num}_pctext_multi.txt')
	with open(text_file, 'w', encoding='utf-8') as _tf:
		_tf.write(wrapped)
	text_file_ff = text_file.replace('\\', '/').replace(':', '\\:')

	dur = max(scene_duration, 0.1)

	_os = max(overlay_start, 0.0)
	_fade_end = _os + 0.5
	alpha_expr = (
		f"if(lt(t,{_os:.3f}),0,"
		f"if(lt(t,{_fade_end:.3f}),(t-{_os:.3f})/0.5,1))"
	)
	alpha_expr = alpha_expr.replace(',', r'\,')

	drawtext = (
		f"drawtext=fontfile='{font_path_ff}'"
		f":textfile='{text_file_ff}'"
		f":fontcolor=white:fontsize=52"
		f":shadowcolor=black@0.7:shadowx=3:shadowy=3"
		f":x=(w-text_w)/2:y=(h-text_h)/2"
		f":alpha='{alpha_expr}'"
	)

	vf = drawtext

	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-i', temp_base,
		'-t', str(dur),
		'-vf', vf,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'S{scene_num} pregunta-capciosa-multi')

	if not ok or not _file_ok(out):
		logger.warning(f"[P4] S{scene_num}: PC overlay on multi-clip failed, using base")
		os.rename(temp_base, out)
		return out

	try:
		os.remove(temp_base)
	except OSError:
		pass
	return out


def _apply_section_title_overlay(
	base_clip_path: str,
	scene_duration: float,
	work_dir: Path,
	scene_num: int,
	text: str,
	overlay_elapsed_before: float = 0.0,
	overlay_duration: float = 3.5,
) -> str:
	"""Apply a chapter-style section title over an already built clip.

	The overlay can span multiple scene clips, so *overlay_elapsed_before* tells
	us how many seconds of the title animation have already happened before this
	particular clip begins.
	"""
	if not text or overlay_duration <= 0.05:
		return base_clip_path

	out = str(work_dir / f'scene_{scene_num}.mp4')
	temp_base = str(work_dir / f'scene_{scene_num}_sectiontitle_base.mp4')
	try:
		if os.path.exists(temp_base):
			os.remove(temp_base)
		os.rename(base_clip_path, temp_base)
	except OSError as e:
		logger.warning(f"[P4] S{scene_num}: rename for section-title overlay failed ({e})")
		return base_clip_path

	_raw_font = os.path.join(
		os.path.dirname(os.path.abspath(__file__)),
		'..', '..', '..', '..', 'workspace_aux', 'assets', 'fonts', 'Montserrat-Black.ttf'
	)
	_raw_font = os.path.normpath(_raw_font)
	font_path_ff = _raw_font.replace('\\', '/').replace(':', '\\:')

	norm_text = (
		str(text)
		.replace('\\n', ' ')
		.replace('\n', ' ')
		.replace('—', '-')
		.replace('–', '-')
	)
	norm_text = ' '.join(norm_text.split())

	max_chars_per_line = 28
	words = norm_text.split()
	lines: list[str] = []
	current_line = ''
	for word in words:
		test = (current_line + ' ' + word).strip()
		if len(test) <= max_chars_per_line:
			current_line = test
		else:
			if current_line:
				lines.append(current_line)
			current_line = word
	if current_line:
		lines.append(current_line)

	dur = max(scene_duration, 0.1)
	elapsed_before = max(0.0, float(overlay_elapsed_before or 0.0))
	visible_duration = max(0.1, float(overlay_duration or 0.0))
	fade_in_dur = min(0.6, visible_duration * 0.35)
	fade_out_dur = min(0.45, visible_duration * 0.3)
	fade_out_start = max(fade_in_dur, visible_duration - fade_out_dur)
	global_t = f"({elapsed_before:.3f}+t)"
	alpha_expr = (
		f"if(lt({global_t},0),0,"
		f"if(lt({global_t},{fade_in_dur:.3f}),{global_t}/{fade_in_dur:.3f},"
		f"if(lt({global_t},{fade_out_start:.3f}),1,"
		f"max(0,1-(({global_t}-{fade_out_start:.3f})/{fade_out_dur:.3f})))))"
	)
	alpha_expr = alpha_expr.replace(',', r'\,')

	font_size = 58
	line_step = 76
	drawtext_parts: list[str] = []
	for idx, line in enumerate(lines if lines else [norm_text]):
		line_file = str(work_dir / f'scene_{scene_num}_section_title_{idx}.txt')
		with open(line_file, 'w', encoding='utf-8') as _tf:
			_tf.write(str(line).replace('%', '%%'))
		line_file_ff = line_file.replace('\\', '/').replace(':', '\\:')
		drawtext_parts.append(
			f"drawtext=fontfile='{font_path_ff}'"
			f":textfile='{line_file_ff}'"
			f":fontcolor=white:fontsize={font_size}"
			f":bordercolor=black@0.88:borderw=4"
			f":shadowcolor=black@0.95:shadowx=5:shadowy=5"
			f":x=74:y={66 + idx * line_step}"
			f":alpha='{alpha_expr}'"
		)
	drawtext = ','.join(drawtext_parts)

	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-i', temp_base,
		'-t', str(dur),
		'-vf', drawtext,
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	], tag=f'S{scene_num} section-title')

	if not ok or not _file_ok(out):
		logger.warning(f"[P4] S{scene_num}: section-title overlay failed, using base clip")
		os.rename(temp_base, out)
		return out

	try:
		os.remove(temp_base)
	except OSError:
		pass
	return out


def _build_multi_clip(clips: list[Proceso4SceneMedia], scene_duration: float, work_dir: Path, scene_num: int) -> str:
	"""Build a multi-clip scene.

	Encodes each clip independently, then either:
	  - Uses FFmpeg xfade filter for clips with non-cut transitions
	  - Concatenates via concat demuxer for pure hard-cut scenes
	Falls back to simple concat if xfade fails.
	"""
	n = len(clips)

	# Mapping of our transition names → FFmpeg xfade transition names
	XFADE_MAP = {
		'dissolve': 'fade',
		'fade_black': 'fadeblack',
		'fade_white': 'fadewhite',
		'wipeleft': 'wipeleft',
		'wiperight': 'wiperight',
	}

	def _xfade_duration(clip: Proceso4SceneMedia) -> float:
		if XFADE_MAP.get(clip.transition_type or 'cut'):
			return clip.transition_duration if (clip.transition_duration or 0.0) > 0.04 else 0.5
		return 0.0

	# Check if any clip has a real non-cut transition.
	has_xfade = any(
		_xfade_duration(clips[i]) > 0.04
		for i in range(n - 1)
	)

	# Effective durations per clip; adjust last so total == scene_duration
	eff_durs = [_effective_clip_duration(c) for c in clips]
	# Subtract transition overlap from total
	transition_overlap_total = 0.0
	if has_xfade:
		for i in range(n - 1):
			transition_overlap_total += _xfade_duration(clips[i])
	total_eff = sum(eff_durs) - transition_overlap_total
	if total_eff > 0 and abs(total_eff - scene_duration) > 0.05:
		eff_durs[-1] = max(0.5, eff_durs[-1] + (scene_duration - total_eff))

	sub_clips: list[str] = []
	for i, clip in enumerate(clips):
		sub_out = str(work_dir / f'scene_{scene_num}_sub_{i}.mp4')
		clip_dur = eff_durs[i]

		if clip.media_type == 'image':
			ok = _build_image_motion_clip(clip, clip_dur, sub_out, scene_num, tag=f'S{scene_num} sub{i} image')
		else:
			if not _ensure_clip_path_local(clip.file_path):
				ok = False
			else:
				spd = clip.speed if clip.speed and clip.speed > 0 else 1.0
				trim_start = clip.trim_start or 0.0
				raw_dur = clip_dur * spd  # source frames to supply before setpts
				if abs(spd - 1.0) > 0.01:
					pts_factor = 1.0 / spd
					vf = f'{_SCALE_VF},setpts={pts_factor:.6f}*PTS'
				else:
					vf = _SCALE_VF
				input_args = (['-ss', str(trim_start)] if trim_start > 0 else []) + ['-i', clip.file_path]
				ok = _run_ffmpeg([
					FFMPEG_BIN, '-y',
					*input_args,
					'-t', str(raw_dur),
					'-vf', vf,
					'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
					sub_out,
				], tag=f'S{scene_num} sub{i} video spd={spd}x')

		if ok and _file_ok(sub_out):
			sub_clips.append(sub_out)
		else:
			# Replace failed sub-clip with a black segment of same duration
			logger.warning(f"[P4] Sub-clip {i} for scene {scene_num} failed — using black segment")
			black_sub = str(work_dir / f'scene_{scene_num}_sub_{i}_black.mp4')
			_run_ffmpeg([
				FFMPEG_BIN, '-y',
				'-f', 'lavfi', '-i', f'color=c=black:s=1920x1080:r=30',
				'-t', str(clip_dur),
				'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
				black_sub,
			], tag=f'S{scene_num} sub{i} black fallback')
			if _file_ok(black_sub):
				sub_clips.append(black_sub)

	if not sub_clips:
		return _build_black_scene(scene_duration, work_dir, scene_num)

	if len(sub_clips) == 1:
		# Single surviving sub-clip: pad to scene_duration
		_pad_to_duration(sub_clips[0], scene_duration, work_dir, scene_num, tag=f'S{scene_num} single-sub')
		return sub_clips[0]

	# ---- Try xfade if any clip uses a non-cut transition ----
	if has_xfade and len(sub_clips) == n:
		xfade_ok = _build_multi_clip_xfade(
			sub_clips, clips, eff_durs, scene_num, work_dir, XFADE_MAP,
		)
		if xfade_ok:
			# Verify xfade output matches expected scene duration
			_pad_to_duration(xfade_ok, scene_duration, work_dir, scene_num, tag=f'S{scene_num} xfade')
			return xfade_ok

		# xfade failed — recalculate eff_durs[-1] WITHOUT the transition overlap
		# deduction, since simple concat doesn't overlap clips.
		if transition_overlap_total > 0:
			logger.info(
				f"[P4] S{scene_num}: xfade fallback -> restoring last clip duration "
				f"(+{transition_overlap_total:.3f}s overlap was subtracted for xfade)"
			)
			# Restore the original total without overlap deduction
			total_no_overlap = sum(eff_durs) + transition_overlap_total  # undo previous adjustment
			# BUT eff_durs[-1] was already adjusted when we had overlap.
			# The original pre-adjustment last dur was:
			#   eff_durs[-1]_orig + (scene_duration - total_eff_with_overlap)
			# We need: sum(eff_durs) == scene_duration (no overlap)
			current_total = sum(eff_durs)
			needed_adjustment = scene_duration - current_total
			eff_durs[-1] = max(0.5, eff_durs[-1] + needed_adjustment)
			# Re-encode the last sub-clip with corrected duration
			last_clip = clips[-1]
			last_sub_out = sub_clips[-1]
			last_dur = eff_durs[-1]
			if last_clip.media_type == 'image':
				_build_image_motion_clip(
					last_clip,
					last_dur,
					last_sub_out,
					scene_num,
					tag=f'S{scene_num} sub{n-1} image (xfade-fallback fix)',
				)
			else:
				trim_start = last_clip.trim_start or 0.0
				_encode_segment(
					last_clip.file_path, is_lavfi=False, out=last_sub_out,
					t=last_dur, ss=trim_start,
					tag=f'S{scene_num} sub{n-1} video (xfade-fallback fix)',
				)

	# ---- Fallback: simple concat (hard cuts) ----
	out = _build_multi_clip_concat(sub_clips, scene_num, work_dir)
	_pad_to_duration(out, scene_duration, work_dir, scene_num, tag=f'S{scene_num} multi-concat')
	return out


def _build_multi_clip_xfade(
	sub_clips: list[str],
	clips: list[Proceso4SceneMedia],
	eff_durs: list[float],
	scene_num: int,
	work_dir: Path,
	xfade_map: dict[str, str],
) -> str | None:
	"""Build a multi-clip scene using FFmpeg xfade filter chain.
	Returns the output path on success, or None on failure.
	"""
	n = len(sub_clips)
	if n < 2:
		return None

	# Build the filter_complex string by chaining xfade between pairs
	# Input labels: [0:v], [1:v], [2:v], ...
	# Chain: [0:v][1:v]xfade=...[v01]; [v01][2:v]xfade=...[v012]; etc.
	filter_parts = []
	for i in range(n):
		filter_parts.append(f'[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[v{i}in]')

	current_duration = eff_durs[0]

	for i in range(n - 1):
		trans_type = clips[i].transition_type or 'cut'
		trans_dur = clips[i].transition_duration or 0.0
		xfade_name = xfade_map.get(trans_type)

		if xfade_name and trans_dur <= 0.04:
			trans_dur = 0.5
		elif not xfade_name or trans_dur <= 0:
			# No transition — use a very tiny dissolve as a "cut" equivalent
			# or just set offset with 0-duration (hard cut within xfade chain)
			xfade_name = 'fade'
			trans_dur = 0.01  # effectively instant

		# Offset is relative to the accumulated output entering this xfade.
		transition_offset = max(0, current_duration - trans_dur)
		in_label_a = '[v0in]' if i == 0 else f'[v{i}]'

		in_label_b = f'[v{i + 1}in]'
		xfade_label = f'[vx{i + 1}]'
		out_label = f'[v{i + 1}]' if i < n - 2 else '[vout]'

		filter_parts.append(
			f'{in_label_a}{in_label_b}xfade=transition={xfade_name}:duration={trans_dur:.3f}:offset={transition_offset:.3f}{xfade_label}'
		)
		filter_parts.append(
			f'{xfade_label}settb=AVTB,setpts=PTS-STARTPTS,fps=30{out_label}'
		)
		current_duration = current_duration + eff_durs[i + 1] - trans_dur

	filter_complex = ';'.join(filter_parts)
	out = str(work_dir / f'scene_{scene_num}.mp4')

	# Build command with all inputs
	cmd = [FFMPEG_BIN, '-y']
	for sc in sub_clips:
		cmd.extend(['-i', sc])
	cmd.extend([
		'-filter_complex', filter_complex,
		'-map', '[vout]',
		'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
		out,
	])

	ok = _run_ffmpeg(cmd, timeout=300, tag=f'S{scene_num} xfade multi')
	if ok and _file_ok(out):
		expected = max(0.1, sum(eff_durs) - sum(
			(
				clips[i].transition_duration
				if (clips[i].transition_duration or 0.0) > 0.04
				else 0.5
			)
			for i in range(n - 1)
			if xfade_map.get(clips[i].transition_type or 'cut')
		))
		actual = _get_clip_duration(out)
		if actual > 0 and actual < expected - 1.0:
			logger.warning(
				f"[P4] Scene {scene_num}: xfade output too short "
				f"({actual:.3f}s < expected {expected:.3f}s), falling back to concat"
			)
			return None
		logger.info(f"[P4] Scene {scene_num}: xfade render successful")
		return out
	else:
		logger.warning(f"[P4] Scene {scene_num}: xfade failed, falling back to simple concat")
		return None


def _build_multi_clip_concat(sub_clips: list[str], scene_num: int, work_dir: Path) -> str:
	"""Concatenate sub-clips with simple hard cuts (no transitions).
	Uses -c copy to avoid frame-boundary rounding drift.
	"""
	concat_list = work_dir / f'scene_{scene_num}_sub_concat.txt'
	with open(concat_list, 'w', encoding='utf-8') as fh:
		for sc in sub_clips:
			fh.write(f"file '{sc}'\n")

	out = str(work_dir / f'scene_{scene_num}.mp4')
	ok = _run_ffmpeg([
		FFMPEG_BIN, '-y',
		'-f', 'concat', '-safe', '0', '-i', str(concat_list),
		'-c', 'copy', '-an',
		out,
	], tag=f'S{scene_num} multi concat')

	# Fallback to re-encode if stream-copy concat fails
	if not ok or not _file_ok(out):
		logger.warning(f'[P4] S{scene_num}: stream-copy sub-concat failed, re-encoding')
		ok = _run_ffmpeg([
			FFMPEG_BIN, '-y',
			'-f', 'concat', '-safe', '0', '-i', str(concat_list),
			'-c:v', VIDEO_ENCODER, '-pix_fmt', 'yuv420p', '-r', '30', '-an',
			out,
		], tag=f'S{scene_num} multi concat (re-encode fallback)')

	if not ok or not _file_ok(out):
		# Last resort: return first valid sub-clip
		logger.error(f"[P4] Multi-clip concat failed for scene {scene_num}, using first sub-clip")
		return sub_clips[0]

	return out
