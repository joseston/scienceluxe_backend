from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB
from aplicacion import db


def utc_now():
	return datetime.now(timezone.utc)


class ClipLibraryItem(db.Model):
	"""Central clip library — reusable media across all projects."""

	__tablename__ = 'clip_library_items'

	id = db.Column(db.Integer, primary_key=True)

	# Deduplication key: SHA-256 of the original file content
	file_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)

	# File info
	original_filename = db.Column(db.String(500), nullable=True)
	file_path = db.Column(db.String(500), nullable=False)  # relative to CLIPS_LIBRARY_DIR/originals/
	media_type = db.Column(db.String(10), nullable=False)  # 'video' | 'image'
	duration = db.Column(db.Float, nullable=True)  # seconds; null for images
	resolution_w = db.Column(db.Integer, nullable=True)
	resolution_h = db.Column(db.Integer, nullable=True)
	file_size_bytes = db.Column(db.BigInteger, nullable=True)

	# Low-res assets
	thumbnail_path = db.Column(db.String(500), nullable=True)
	proxy_path = db.Column(db.String(500), nullable=True)

	# Content metadata (auto-populated from P3 scene when available)
	visual_type = db.Column(db.String(50), nullable=True)  # Animation, Graphic, B-roll, Stock, Text, Screen Recording, Other
	visual_description = db.Column(db.Text, nullable=True)
	physical_composition = db.Column(db.Text, nullable=True)

	# Searchable metadata
	keywords = db.Column(JSONB, nullable=True, default=list)  # auto-extracted + manual
	tags = db.Column(JSONB, nullable=True, default=list)  # user-defined categories

	# Origin tracking
	source_type = db.Column(db.String(30), nullable=True)  # ai_generated, recorded, stock, downloaded, unknown
	source_info = db.Column(JSONB, nullable=True)  # {generator, prompt, original_project_id, original_scene_num}

	# Semantic search — pgvector (768-dim Gemini text-embedding-004)
	# Column created via raw SQL in migration since SQLAlchemy needs pgvector extension
	# embedding = Column(Vector(768))  — added in migration

	# Full-text search
	# search_text TSVECTOR — added in migration, auto-updated via trigger

	# Usage stats
	usage_count = db.Column(db.Integer, nullable=False, default=0)
	is_favorite = db.Column(db.Boolean, nullable=False, default=False)

	created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
	updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

	def to_dict(self):
		return {
			'id': self.id,
			'fileHash': self.file_hash,
			'originalFilename': self.original_filename,
			'filePath': self.file_path,
			'mediaType': self.media_type,
			'duration': self.duration,
			'resolutionW': self.resolution_w,
			'resolutionH': self.resolution_h,
			'fileSizeBytes': self.file_size_bytes,
			'hasThumbnail': bool(self.thumbnail_path),
			'hasProxy': bool(self.proxy_path),
			'visualType': self.visual_type,
			'visualDescription': self.visual_description,
			'physicalComposition': self.physical_composition,
			'keywords': self.keywords or [],
			'tags': self.tags or [],
			'sourceType': self.source_type,
			'sourceInfo': self.source_info or {},
			'usageCount': self.usage_count,
			'isFavorite': self.is_favorite,
			'createdAt': self.created_at.isoformat() if self.created_at else None,
			'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
		}


class ClipLibraryUsage(db.Model):
	"""Tracks where each library clip has been used."""

	__tablename__ = 'clip_library_usages'

	id = db.Column(db.Integer, primary_key=True)
	clip_id = db.Column(
		db.Integer,
		db.ForeignKey('clip_library_items.id', ondelete='CASCADE'),
		nullable=False,
		index=True,
	)
	proceso1_job_id = db.Column(db.Integer, nullable=False, index=True)
	scene_num = db.Column(db.Integer, nullable=True)
	scene_media_id = db.Column(db.Integer, nullable=True)
	used_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

	def to_dict(self):
		return {
			'id': self.id,
			'clipId': self.clip_id,
			'proceso1JobId': self.proceso1_job_id,
			'sceneNum': self.scene_num,
			'sceneMediaId': self.scene_media_id,
			'usedAt': self.used_at.isoformat() if self.used_at else None,
		}


__all__ = [
	'ClipLibraryItem',
	'ClipLibraryUsage',
]
