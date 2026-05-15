"""
Proceso 4 — Video Assembly
===========================
Endpoints for the custom video assembler.
Imports timeline from Proceso 3, allows media upload per scene,
editing params, audio tracks, and video rendering via FFmpeg.
"""
from __future__ import annotations

from flask import Blueprint
import logging

proceso4_bp = Blueprint('proceso4', __name__)
logger = logging.getLogger(__name__)

# Import submodules to register routes and shared utilities
from . import constants
from . import ffmpeg_setup
from . import helpers
from . import render_ffmpeg
from .routes import assets
from .routes import indice
from .routes import job
from .routes import timeline
from .routes import media
from .routes import preview
from .routes import audio_tracks
from .routes import render
from .routes import prompt_station

# Re-export shared symbols for backward compatibility (proceso4_corto, etc.)
from .ffmpeg_setup import (
	FFMPEG_BIN,
	FFPROBE_BIN,
	VIDEO_ENCODER,
	USE_NVENC,
)
from .helpers import (
	_get_video_duration,
	_parse_mp4_duration,
	_generate_proxy,
)
