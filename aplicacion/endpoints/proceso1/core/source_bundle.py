"""
Source Bundle -- Utilities for building the canonical source input used by Proceso 1.

This module centralizes:
- extraction orchestration
- legacy fallback loading
- placeholder detection
- normalized raw source text assembly
"""
from __future__ import annotations

from pathlib import Path
import sys

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1Source


SIMULATED_CONTENT_MARKER = 'Contenido extraído exitosamente (sincronizado con backend Flask).'


def ensure_workspace_imports() -> None:
    workspace_root = Path(__file__).resolve().parents[4]
    workspace_root_str = str(workspace_root)
    if workspace_root_str not in sys.path:
        sys.path.append(workspace_root_str)


def is_placeholder_content(text: str | None) -> bool:
    if not text:
        return True
    normalized = text.strip().lower()
    return normalized.startswith('contenido extraído exitosamente') or normalized.startswith('contenido extraido exitosamente')


def load_legacy_sources_by_external_id(project_external_id: str) -> list[dict]:
    try:
        ensure_workspace_imports()
        from core.database import db_session, Project, Source

        with db_session() as session:
            project = session.query(Project).filter(Project.external_id == str(project_external_id)).first()
            if not project:
                return []

            rows = session.query(Source).filter(Source.project_id == project.id).order_by(Source.id.asc()).all()
            return [
                {
                    'identificador': row.identificador,
                    'titulo': row.titulo,
                    'contenido': row.contenido,
                    'source_type': row.source_type,
                }
                for row in rows
            ]
    except Exception:
        return []


def extract_sources_for_job(job: Proceso1Job) -> None:
    ensure_workspace_imports()
    from .url_parser import extract_youtube_id
    from .youtube_extractor import extract_transcript
    from .article_extractor import extract_article

    for source in job.sources:
        source.status = 'processing'
        source.error_message = None
        db.session.flush()

        try:
            if source.source_type == 'video':
                video_id = extract_youtube_id(source.url)
                if not video_id:
                    raise ValueError('No se pudo extraer video_id desde URL de YouTube')
                extracted = extract_transcript(video_id)
            else:
                extracted = extract_article(source.url)

            source.title = extracted.get('titulo') or source.title
            source.extracted_content = extracted.get('contenido') or ''
            source.status = extracted.get('status', 'success')
            source.error_message = extracted.get('error')

            if source.status != 'success' and not source.error_message:
                source.error_message = 'Error de extracción sin detalle'

        except Exception as exc:
            source.status = 'error'
            source.error_message = str(exc)
            source.extracted_content = source.extracted_content or ''

    statuses = {s.status for s in job.sources}
    if statuses and statuses.issubset({'success'}):
        job.status = 'completed'
    elif 'error' in statuses:
        job.status = 'completed_with_errors'
    else:
        job.status = 'processing'

    db.session.commit()


def list_job_sources(job_id: int) -> list[Proceso1Source]:
    return Proceso1Source.query.filter_by(job_id=job_id).order_by(Proceso1Source.source_index.asc()).all()


def needs_real_extraction(sources: list[Proceso1Source]) -> bool:
    return any(
        (not (source.extracted_content or '').strip())
        or SIMULATED_CONTENT_MARKER in (source.extracted_content or '')
        for source in sources
    )


def serialize_sources_for_prompt(sources: list[Proceso1Source]) -> list[dict]:
    return [
        {
            'titulo': source.title or 'Source',
            'texto': source.extracted_content or '',
            'tipo': source.source_type,
        }
        for source in sources
    ]


def _resolve_source_text(
    source: Proceso1Source,
    legacy_sources: list[dict],
    use_legacy_fallback: bool,
    fallback_to_url: bool,
) -> str:
    text = source.extracted_content or ''

    if use_legacy_fallback and is_placeholder_content(text):
        matched = next(
            (
                item for item in legacy_sources
                if item.get('identificador') and item.get('identificador') == source.url and item.get('contenido')
            ),
            None,
        )
        if matched is None:
            same_index = source.source_index - 1
            if 0 <= same_index < len(legacy_sources):
                candidate = legacy_sources[same_index]
                if candidate.get('contenido'):
                    matched = candidate

        if matched is not None and matched.get('contenido'):
            text = str(matched.get('contenido'))
            source.extracted_content = text
            if not source.title and matched.get('titulo'):
                source.title = str(matched.get('titulo'))

    if not text and fallback_to_url:
        text = source.url or ''

    return text


def build_source_bundle(
    job: Proceso1Job,
    *,
    ensure_extracted: bool = False,
    use_legacy_fallback: bool = True,
    fallback_to_url: bool = True,
) -> dict:
    sources = list_job_sources(job.id)
    if not sources:
        return {
            'sources': [],
            'source_count': 0,
            'raw_text': '',
            'items': [],
        }

    if ensure_extracted and needs_real_extraction(sources):
        extract_sources_for_job(job)
        sources = list_job_sources(job.id)

    legacy_sources = load_legacy_sources_by_external_id(str(job.video_id)) if use_legacy_fallback else []

    raw_chunks: list[str] = []
    items: list[dict] = []
    for source in sources:
        text = _resolve_source_text(
            source,
            legacy_sources,
            use_legacy_fallback=use_legacy_fallback,
            fallback_to_url=fallback_to_url,
        )
        raw_chunks.append(f"[{source.source_index}] {source.source_type.upper()} - {source.title or 'Fuente'}\n{text}")
        items.append(
            {
                'sourceIndex': source.source_index,
                'title': source.title or 'Fuente',
                'text': text,
                'type': source.source_type,
                'url': source.url,
            }
        )

    return {
        'sources': sources,
        'source_count': len(sources),
        'raw_text': "\n\n".join(raw_chunks),
        'items': items,
    }
