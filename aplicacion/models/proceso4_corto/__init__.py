from datetime import datetime, timezone

from aplicacion import db


def utc_now():
	return datetime.now(timezone.utc)


class Proceso4CortoJob(db.Model):
	"""Proceso 4 Corto – Video Assembly for shorts. Linked to Proceso1CortoJob."""

	__tablename__ = 'proceso4_corto_jobs'

	proceso1_corto_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'),
		primary_key=True,
	)
	status = db.Column(db.String(50), nullable=False, default='created')
	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'proceso1CortoJobId': self.proceso1_corto_job_id,
			'status': self.status,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4CortoSubprocessState(db.Model):
	__tablename__ = 'proceso4_corto_subprocess_states'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_corto_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'),
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
		db.UniqueConstraint('proceso1_corto_job_id', 'subprocess_key', name='uq_p4c_job_subprocess_key'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1CortoJobId': self.proceso1_corto_job_id,
			'subprocessKey': self.subprocess_key,
			'status': self.status,
			'input': self.input_payload or {},
			'output': self.output_payload or {},
			'metadata': self.metadata_payload or {},
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4CortoSceneMedia(db.Model):
	"""Media (video/image) assigned to a scene in the short video assembly."""

	__tablename__ = 'proceso4_corto_scene_media'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_corto_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	scene_num = db.Column(db.Integer, nullable=False)
	clip_index = db.Column(db.Integer, nullable=False, default=0)

	# Media info
	media_type = db.Column(db.String(10), nullable=False)  # 'video' or 'image'
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)
	duration = db.Column(db.Float, nullable=True)

	# Editing params
	trim_start = db.Column(db.Float, nullable=False, default=0.0)
	trim_end = db.Column(db.Float, nullable=True)
	speed = db.Column(db.Float, nullable=False, default=1.0)
	transition_type = db.Column(db.String(30), nullable=False, default='cut')
	transition_duration = db.Column(db.Float, nullable=False, default=0.0)

	# Low-resolution proxy file for preview
	proxy_path = db.Column(db.String(500), nullable=True)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	__table_args__ = (
		db.UniqueConstraint('proceso1_corto_job_id', 'scene_num', 'clip_index', name='uq_p4c_scene_clip'),
	)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1CortoJobId': self.proceso1_corto_job_id,
			'sceneNum': self.scene_num,
			'clipIndex': self.clip_index,
			'mediaType': self.media_type,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'duration': self.duration,
			'trimStart': self.trim_start,
			'trimEnd': self.trim_end,
			'speed': self.speed,
			'transitionType': self.transition_type,
			'transitionDuration': self.transition_duration,
			'hasProxy': bool(self.proxy_path),
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class Proceso4CortoAudioTrack(db.Model):
	"""Optional music/sfx track for short video assembly."""

	__tablename__ = 'proceso4_corto_audio_tracks'

	id = db.Column(db.Integer, primary_key=True)
	proceso1_corto_job_id = db.Column(
		db.Integer,
		db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	track_type = db.Column(db.String(20), nullable=False, default='music')
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)
	start_time = db.Column(db.Float, nullable=False, default=0.0)
	volume = db.Column(db.Float, nullable=False, default=0.3)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'id': self.id,
			'proceso1CortoJobId': self.proceso1_corto_job_id,
			'trackType': self.track_type,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'startTime': self.start_time,
			'volume': self.volume,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


__all__ = [
	'Proceso4CortoJob',
	'Proceso4CortoSubprocessState',
	'Proceso4CortoSceneMedia',
	'Proceso4CortoAudioTrack',
]
