from datetime import datetime, timezone

from aplicacion import db


def utc_now():
	return datetime.now(timezone.utc)


class Proceso5Job(db.Model):
	"""Proceso 5 – Empaquetado y Metadatos Finales."""

	__tablename__ = 'proceso5_jobs'

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


class Proceso5SubprocessState(db.Model):
	"""Estados de los distintos pasos de empacado (e.g. metadata_generation)."""

	__tablename__ = 'proceso5_subprocess_states'

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
		db.UniqueConstraint('proceso1_job_id', 'subprocess_key', name='uq_proceso5_job_subprocess_key'),
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

__all__ = [
	'Proceso5Job',
	'Proceso5SubprocessState',
]
