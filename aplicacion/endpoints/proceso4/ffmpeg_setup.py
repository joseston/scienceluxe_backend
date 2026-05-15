from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe binary resolution
# ---------------------------------------------------------------------------
# The conda env may have broken binaries.  We search for a working copy that
# also supports libx264 (full encoding capability required for render).

def _binary_has_libx264(path: str) -> bool:
	"""Return True if the ffmpeg binary supports libx264 encoding."""
	try:
		r = subprocess.run([path, '-encoders'], capture_output=True, timeout=8)
		return b'libx264' in r.stdout
	except Exception:
		return False


def _is_working_binary(path: str, require_libx264: bool = False) -> bool:
	"""Return True when the binary starts correctly and meets optional codec requirements."""
	try:
		r = subprocess.run([path, '-version'], capture_output=True, timeout=5)
		if r.returncode != 0:
			return False
		if require_libx264 and not _binary_has_libx264(path):
			return False
		return True
	except Exception:
		return False


def _find_working_binary(name: str, require_libx264: bool = False) -> str:
	"""Return an absolute path to a working ffmpeg/ffprobe binary.

	If require_libx264=True (for ffmpeg), prefer binaries that have libx264.
	"""
	import shutil as _shutil

	env_var_name = f'{name.upper()}_BIN'
	explicit_path = os.environ.get(env_var_name, '').strip()
	if explicit_path:
		bad_explicit_parts = (
			'ffmpeg-8.0.1-gpl_hb2d76f6_912',
			'envs\\scienceluxe\\Library\\bin',
		)
		if any(part.lower() in explicit_path.lower() for part in bad_explicit_parts):
			logger.warning(f'[P4] Ignoring known problematic ${env_var_name}: {explicit_path}')
		elif Path(explicit_path).exists():
			logger.info(f'[P4] Using {name} from ${env_var_name}: {explicit_path}')
			return explicit_path
		else:
			logger.warning(f'[P4] Ignoring missing ${env_var_name}: {explicit_path}')

	# Resolve miniconda root independent of which env is active
	conda_prefix = os.environ.get('CONDA_PREFIX', '')
	if conda_prefix:
		candidate_root = Path(conda_prefix).parent.parent  # …/miniconda3
	else:
		candidate_root = Path.home() / 'miniconda3'
	if not candidate_root.exists():
		candidate_root = Path('C:/Users') / os.environ.get('USERNAME', 'JOSE') / 'miniconda3'

	current_env_candidate = None
	if conda_prefix:
		current_env_candidate = Path(conda_prefix) / 'Library' / 'bin' / f'{name}.exe'

	candidates: list[Path] = []
	candidates += sorted(candidate_root.glob(f'pkgs/ffmpeg-*/Library/bin/{name}.exe'), reverse=True)
	candidates += [
		path for path in sorted(candidate_root.glob(f'envs/*/Library/bin/{name}.exe'))
		if not current_env_candidate or path.resolve() != current_env_candidate.resolve()
	]

	on_path = _shutil.which(name)
	if on_path:
		candidates.append(Path(on_path))

	if current_env_candidate:
		candidates.append(current_env_candidate)

	known_bad_parts = (
		'ffmpeg-8.0.1-gpl_hb2d76f6_912',
		'envs\\scienceluxe\\Library\\bin',
	)

	seen: set[str] = set()
	for cand in candidates:
		cand_str = str(cand)
		cand_key = cand_str.lower()
		if any(part.lower() in cand_key for part in known_bad_parts):
			logger.warning(f'[P4] Skipping known problematic {name}: {cand_str}')
			continue
		if cand_str in seen:
			continue
		seen.add(cand_str)
		if _is_working_binary(cand_str, require_libx264=require_libx264):
			if require_libx264:
				logger.info(f'[P4] Using {name} with libx264 at {cand_str}')
			else:
				logger.info(f'[P4] Using {name} at {cand_str}')
			return cand_str

	logger.warning(f'[P4] No working {name} binary found! Falling back to bare name.')
	return name


def _detect_video_encoder(ffmpeg_bin: str) -> str:
	"""Return the best available H.264 encoder.

	Priority: h264_nvenc (GPU) > libx264 (CPU) > h264_mf (Windows) > mpeg4
	"""
	try:
		r = subprocess.run([ffmpeg_bin, '-encoders'], capture_output=True, timeout=8)
		out = r.stdout
		if b'h264_nvenc' in out:
			return 'h264_nvenc'
		if b'libx264' in out:
			return 'libx264'
		if b'h264_mf' in out:
			return 'h264_mf'
		if b'mpeg4' in out:
			return 'mpeg4'
	except Exception:
		pass
	return 'libx264'  # last resort


FFPROBE_BIN = _find_working_binary('ffprobe', require_libx264=False)
FFMPEG_BIN  = _find_working_binary('ffmpeg',  require_libx264=True)
VIDEO_ENCODER = _detect_video_encoder(FFMPEG_BIN)
USE_NVENC = VIDEO_ENCODER == 'h264_nvenc'
logger.info(f'[P4] FFMPEG_BIN={FFMPEG_BIN} | VIDEO_ENCODER={VIDEO_ENCODER} | GPU={USE_NVENC}')
