from __future__ import annotations

from pathlib import Path

from .prompt_templates import SECTIONS_ORDER

PISTAS_DIR = Path(r'D:\scienceluxe_2026\pistas')

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
