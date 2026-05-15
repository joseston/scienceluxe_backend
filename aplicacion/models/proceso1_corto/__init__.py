from datetime import datetime, timezone

from aplicacion import db


def utc_now():
    return datetime.now(timezone.utc)


class Proceso1CortoJob(db.Model):
    __tablename__ = 'proceso1_corto_jobs'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(120), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='created')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    sources = db.relationship(
        'Proceso1CortoSource',
        backref='job',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='Proceso1CortoSource.source_index.asc()'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'videoId': self.video_id,
            'status': self.status,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'sources': [source.to_dict() for source in self.sources],
        }


class Proceso1CortoSource(db.Model):
    __tablename__ = 'proceso1_corto_sources'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'), nullable=False, index=True)
    source_index = db.Column(db.Integer, nullable=False)
    url = db.Column(db.Text, nullable=False)
    source_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='pending')
    title = db.Column(db.String(255), nullable=True)
    extracted_content = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint('job_id', 'source_index', name='uq_proceso1_corto_source_job_index'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'jobId': self.job_id,
            'sourceIndex': self.source_index,
            'url': self.url,
            'type': self.source_type,
            'status': self.status,
            'title': self.title,
            'extractedContent': self.extracted_content,
            'errorMessage': self.error_message,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }


class Proceso1CortoSubprocessState(db.Model):
    __tablename__ = 'proceso1_corto_subprocess_states'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('proceso1_corto_jobs.id', ondelete='CASCADE'), nullable=False, index=True)
    subprocess_key = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='draft')
    input_payload = db.Column(db.JSON, nullable=True)
    output_payload = db.Column(db.JSON, nullable=True)
    metadata_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint('job_id', 'subprocess_key', name='uq_proceso1_corto_job_subprocess_key'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'jobId': self.job_id,
            'subprocessKey': self.subprocess_key,
            'status': self.status,
            'input': self.input_payload or {},
            'output': self.output_payload or {},
            'metadata': self.metadata_payload or {},
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }
