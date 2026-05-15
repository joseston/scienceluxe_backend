from datetime import datetime, timezone

from aplicacion import db


def utc_now():
	return datetime.now(timezone.utc)


class Proceso4Job(db.Model):
	"""Proceso 4 – Ensamblaje de video. Se ancla al mismo ID del Job de Proceso 1."""

	__tablename__ = 'proceso4_jobs'

	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		primary_key=True,
	)
	status = db.Column(db.String(50), nullable=False, default='created')
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'proceso1JobId': self.proceso1_job_id,
			'status': self.status,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4SubprocessState(db.Model):
	__tablename__ = 'proceso4_subprocess_states'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	subprocess_key = db.Column(db.String(50), nullable=False)
	status = db.Column(db.String(50), nullable=False, default='draft')
	input_payload = db.Column(db.JSON, nullable=True)
	output_payload = db.Column(db.JSON, nullable=True)
	metadata_payload = db.Column(db.JSON, nullable=True)
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	__table_args__ = (
		db.UniqueConstraint('proceso1_job_id', 'subprocess_key', name='uq_proceso4_job_subprocess_key'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1JobId': self.proceso1_job_id,
			'subprocessKey': self.subprocess_key,
			'status': self.status,
			'input': self.input_payload or {},
			'output': self.output_payload or {},
			'metadata': self.metadata_payload or {},
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4SceneMedia(db.Model):
	"""Media (video/image) assigned to a scene in the video assembly."""

	__tablename__ = 'proceso4_scene_media'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	scene_num = db.Column(db.Integer, nullable=False)
	clip_index = db.Column(db.Integer, nullable=False, default=0)

	# Media info
	media_type = db.Column(db.String(10), nullable=False)  # 'video' or 'image'
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)
	duration = db.Column(db.Float, nullable=True)  # original duration if video

	# Editing params
	trim_start = db.Column(db.Float, nullable=False, default=0.0)
	trim_end = db.Column(db.Float, nullable=True)  # null = use full clip
	speed = db.Column(db.Float, nullable=False, default=1.0)  # playback speed (0.25–4.0); 2.0 = 2x fast
	# Still-image motion (used only when media_type == 'image')
	image_motion_preset = db.Column(db.String(40), nullable=False, default='auto')
	image_motion_intensity = db.Column(db.String(20), nullable=False, default='medium')
	# Transition to next clip within same scene
	transition_type = db.Column(db.String(30), nullable=False, default='cut')  # cut, dissolve, fade_black, fade_white
	transition_duration = db.Column(db.Float, nullable=False, default=0.5)
	# Optional sound effect for the transition (filename from shared SFX folder)
	transition_sound = db.Column(db.String(500), nullable=True)  # e.g. 'whoosh.mp3'

	# Optional text overlay config — used for ÍNDICE auto-generated clips
	# Format: {"lines": ["Subtema 1", "Subtema 2", ...], "style": "indice"}
	text_overlay = db.Column(db.JSON, nullable=True)

	# Low-resolution proxy file for preview (generated on upload for videos)
	proxy_path = db.Column(db.String(500), nullable=True)

	# Reference to the central clip library (null = uploaded directly, not from library)
	library_clip_id = db.Column(
		db.Integer,
		db.ForeignKey('clip_library_items.id', ondelete='SET NULL'),
		nullable=True,
		index=True,
	)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	__table_args__ = (
		db.UniqueConstraint('proceso1_job_id', 'scene_num', 'clip_index', name='uq_proceso4_scene_clip'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1JobId': self.proceso1_job_id,
			'sceneNum': self.scene_num,
			'clipIndex': self.clip_index,
			'mediaType': self.media_type,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'duration': self.duration,
			'trimStart': self.trim_start,
			'trimEnd': self.trim_end,
			'speed': self.speed,
			'imageMotionPreset': self.image_motion_preset or 'auto',
			'imageMotionIntensity': self.image_motion_intensity or 'medium',
			'transitionType': self.transition_type,
			'transitionDuration': self.transition_duration,
			'transitionSound': self.transition_sound,
			'textOverlay': self.text_overlay,
			'hasProxy': bool(self.proxy_path),
			'libraryClipId': self.library_clip_id,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4AudioTrack(db.Model):
	"""Extra audio tracks (music, sfx) for the video assembly."""

	__tablename__ = 'proceso4_audio_tracks'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	track_type = db.Column(db.String(20), nullable=False, default='music')  # music, sfx
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)
	start_time = db.Column(db.Float, nullable=False, default=0.0)
	volume = db.Column(db.Float, nullable=False, default=0.3)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1JobId': self.proceso1_job_id,
			'trackType': self.track_type,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'startTime': self.start_time,
			'volume': self.volume,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4GlobalAsset(db.Model):
	"""Global reusable assets shared across all Proceso 4 projects.

	asset_key examples: 'indice_image', 'indice_music'
	"""

	__tablename__ = 'proceso4_global_assets'

	id = db.Column(db.Integer, primary_key=True)
	asset_key = db.Column(db.String(50), nullable=False, unique=True)
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'id': self.id,
			'assetKey': self.asset_key,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4SectionTrack(db.Model):
	"""Pista musical asignada a una sección del video (intro, subtema_1..4, cierre)."""

	__tablename__ = 'proceso4_section_tracks'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	section = db.Column(db.String(30), nullable=False)  # intro, subtema_1..4, cierre
	pista_filename = db.Column(db.String(500), nullable=False)
	pista_path = db.Column(db.String(500), nullable=False)
	volume = db.Column(db.Float, nullable=False, default=0.15)
	fade_in = db.Column(db.Float, nullable=False, default=1.0)
	fade_out = db.Column(db.Float, nullable=False, default=2.0)
	start_offset = db.Column(db.Float, nullable=False, default=0.0)  # seconds into the pista to start playback

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	__table_args__ = (
		db.UniqueConstraint('proceso1_job_id', 'section', name='uq_p4_section_track'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1JobId': self.proceso1_job_id,
			'section': self.section,
			'pistaFilename': self.pista_filename,
			'pistaPath': self.pista_path,
			'volume': self.volume,
			'fadeIn': self.fade_in,
			'fadeOut': self.fade_out,
			'startOffset': self.start_offset,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4MusicTemplate(db.Model):
	"""Plantilla global reutilizable de pistas musicales por seccion."""

	__tablename__ = 'proceso4_music_templates'

	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String(120), nullable=False, unique=True, index=True)
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	items = db.relationship(
		'Proceso4MusicTemplateItem',
		backref='template',
		lazy=True,
		cascade='all, delete-orphan',
		order_by='Proceso4MusicTemplateItem.section.asc()',
	)

	def to_dict(self):
		return {
			'id': self.id,
			'name': self.name,
			'itemCount': len(self.items or []),
			'items': [item.to_dict() for item in (self.items or [])],
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4MusicTemplateItem(db.Model):
	"""Item por seccion dentro de una plantilla musical."""

	__tablename__ = 'proceso4_music_template_items'

	id = db.Column(db.Integer, primary_key=True)
	template_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso4_music_templates.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	section = db.Column(db.String(30), nullable=False)
	pista_filename = db.Column(db.String(500), nullable=False)
	volume = db.Column(db.Float, nullable=False, default=0.15)
	fade_in = db.Column(db.Float, nullable=False, default=1.0)
	fade_out = db.Column(db.Float, nullable=False, default=2.0)
	start_offset = db.Column(db.Float, nullable=False, default=0.0)
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	__table_args__ = (
		db.UniqueConstraint('template_id', 'section', name='uq_p4_music_template_item_section'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'section': self.section,
			'pistaFilename': self.pista_filename,
			'volume': self.volume,
			'fadeIn': self.fade_in,
			'fadeOut': self.fade_out,
			'startOffset': self.start_offset,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4ReverbConfig(db.Model):
	"""Configuración de reverb para la narración del video."""

	__tablename__ = 'proceso4_reverb_config'

	proceso1_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_jobs.id', ondelete='CASCADE'),
		primary_key=True,
	)
	enabled = db.Column(db.Boolean, nullable=False, default=True)
	in_gain = db.Column(db.Float, nullable=False, default=0.8)
	out_gain = db.Column(db.Float, nullable=False, default=0.88)
	delay_ms = db.Column(db.Float, nullable=False, default=60.0)
	decay = db.Column(db.Float, nullable=False, default=0.4)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'proceso1JobId': self.proceso1_job_id,
			'enabled': self.enabled,
			'inGain': self.in_gain,
			'outGain': self.out_gain,
			'delayMs': self.delay_ms,
			'decay': self.decay,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


__all__ = [
	'Proceso4Job',
	'Proceso4SubprocessState',
	'Proceso4SceneMedia',
	'Proceso4AudioTrack',
	'Proceso4GlobalAsset',
	'Proceso4SectionTrack',
	'Proceso4MusicTemplate',
	'Proceso4MusicTemplateItem',
	'Proceso4ReverbConfig',
]
