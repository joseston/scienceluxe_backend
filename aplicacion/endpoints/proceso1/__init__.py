from flask import Blueprint, jsonify, request

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1Source, Proceso1SubprocessState
from .core.source_bundle import (
    build_source_bundle,
    extract_sources_for_job as _extract_sources_for_job_service,
    is_placeholder_content as _is_placeholder_content_service,
    load_legacy_sources_by_external_id as _load_legacy_sources_by_external_id_service,
)
from .core.story_architecture import (
    complete_hybrid_story_structure,
    resolve_prompt_mode,
    run_story_structure_stage,
)


proceso1_bp = Blueprint('proceso1', __name__)
MAX_PROCESO1_SOURCES = 4


def detect_source_type(url: str) -> str:
    normalized = (url or '').lower()
    if 'youtube.com' in normalized or 'youtu.be' in normalized:
        return 'video'
    return 'article'


def _normalize_source_urls(urls: object) -> list[str]:
    if not isinstance(urls, list):
        raise ValueError('urls must be an array')

    normalized_urls = [str(url).strip() for url in urls if str(url).strip()]
    if len(normalized_urls) > MAX_PROCESO1_SOURCES:
        raise ValueError(f'Maximum {MAX_PROCESO1_SOURCES} URLs are allowed')
    return normalized_urls


def _clear_job_subprocess_states(job_id: int) -> None:
    Proceso1SubprocessState.query.filter_by(job_id=job_id).delete(synchronize_session=False)


def _sync_job_sources(job: Proceso1Job, urls: list[str]) -> None:
    existing_sources = sorted(job.sources, key=lambda item: item.source_index)

    for index, url in enumerate(urls, start=1):
        source_type = detect_source_type(url)
        source = existing_sources[index - 1] if index - 1 < len(existing_sources) else None

        if source is None:
            source = Proceso1Source(job_id=job.id)
            db.session.add(source)

        source.source_index = index
        source.url = url
        source.source_type = source_type
        source.status = 'pending'
        source.title = f'Fuente {index}'
        source.extracted_content = ''
        source.error_message = None

    for source in existing_sources[len(urls):]:
        db.session.delete(source)

    _clear_job_subprocess_states(job.id)
    job.status = 'processing' if urls else 'draft'


def get_or_create_subprocess_state(job_id: int, subprocess_key: str) -> Proceso1SubprocessState:
    state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key=subprocess_key).first()
    if state is None:
        state = Proceso1SubprocessState(job_id=job_id, subprocess_key=subprocess_key)
        db.session.add(state)
    return state


def _get_selected_title(job_id: int) -> str:
    """Retrieve the selected title from the Job model (primary source)."""
    job = Proceso1Job.query.get(job_id)
    if job and job.selected_title:
        return job.selected_title
    return ''


def is_placeholder_content(text: str | None) -> bool:
    return _is_placeholder_content_service(text)

    if not text:
        return True
    normalized = text.strip().lower()
    return normalized.startswith('contenido extraído exitosamente') or normalized.startswith('contenido extraido exitosamente')


def load_legacy_sources_by_external_id(project_external_id: str) -> list[dict]:
    return _load_legacy_sources_by_external_id_service(project_external_id)

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


SIMULATED_CONTENT_MARKER = 'Contenido extraído exitosamente (sincronizado con backend Flask).'


def extract_sources_for_job(job: Proceso1Job):
    return _extract_sources_for_job_service(job)

    ensure_workspace_imports()
    from .core.url_parser import extract_youtube_id
    from .core.youtube_extractor import extract_transcript
    from .core.article_extractor import extract_article

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


@proceso1_bp.route('/jobs/<int:job_id>/extract', methods=['POST'])
def run_extraction(job_id: int):
    job = Proceso1Job.query.get_or_404(job_id)
    extract_sources_for_job(job)
    return jsonify(job.to_dict())


@proceso1_bp.route('/jobs', methods=['POST'])
def create_job():
    payload = request.get_json(silent=True) or {}
    video_id = (payload.get('videoId') or '').strip()
    urls = payload.get('urls') or []

    if not video_id:
        return jsonify({'error': 'videoId is required'}), 400

    try:
        normalized_urls = _normalize_source_urls(urls)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    # If no URLs, create as draft (Proceso 0 flow); otherwise processing
    status = 'draft' if not normalized_urls else 'processing'
    job = Proceso1Job(video_id=video_id, status=status)

    # Set North Star fields
    sel_title = (payload.get('selectedTitle') or '').strip()
    sel_thumb = (payload.get('selectedThumbnailPrompt') or '').strip()
    if sel_title:
        job.selected_title = sel_title
    if sel_thumb:
        job.selected_thumbnail_prompt = sel_thumb

    # Set Proceso 0 origin fields
    raw_idea = (payload.get('rawIdea') or '').strip()
    draft_id = (payload.get('draftId') or '').strip()
    if raw_idea:
        job.raw_idea = raw_idea
    if draft_id:
        job.draft_id = draft_id

    db.session.add(job)
    db.session.flush()

    _sync_job_sources(job, normalized_urls)

    db.session.commit()
    return jsonify(job.to_dict()), 201


@proceso1_bp.route('/jobs/<int:job_id>/sources', methods=['POST'])
def add_sources(job_id: int):
    """Replace the current source list for a Job and reset derived extraction state."""
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}
    urls = payload.get('urls') or []

    try:
        normalized_urls = _normalize_source_urls(urls)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not normalized_urls:
        return jsonify({'error': 'At least one URL is required'}), 400

    _sync_job_sources(job, normalized_urls)
    db.session.commit()
    return jsonify(job.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/north-star', methods=['PATCH'])
def update_north_star(job_id: int):
    """Save or update the North Star data (title + thumbnail prompt) on a Job."""
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    sel_title = payload.get('selectedTitle')
    sel_thumb = payload.get('selectedThumbnailPrompt')

    if sel_title is not None:
        job.selected_title = str(sel_title).strip() or None
    if sel_thumb is not None:
        job.selected_thumbnail_prompt = str(sel_thumb).strip() or None

    db.session.commit()
    return jsonify(job.to_dict())


@proceso1_bp.route('/jobs', methods=['GET'])
def list_jobs():
    limit = request.args.get('limit', default=20, type=int)
    jobs = Proceso1Job.query.order_by(Proceso1Job.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return jsonify({'items': [job.to_dict() for job in jobs]})


@proceso1_bp.route('/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id: int):
    job = Proceso1Job.query.get_or_404(job_id)
    return jsonify(job.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/sources/<int:source_id>', methods=['PATCH'])
def update_source(job_id: int, source_id: int):
    source = Proceso1Source.query.filter_by(id=source_id, job_id=job_id).first_or_404()
    payload = request.get_json(silent=True) or {}

    allowed_statuses = {'pending', 'processing', 'success', 'error'}
    status = payload.get('status')
    if status is not None:
        if status not in allowed_statuses:
            return jsonify({'error': 'Invalid status'}), 400
        source.status = status

    if 'title' in payload:
        source.title = payload.get('title')

    if 'extractedContent' in payload:
        source.extracted_content = payload.get('extractedContent')

    if 'errorMessage' in payload:
        source.error_message = payload.get('errorMessage')

    job = Proceso1Job.query.get(job_id)
    if job is not None:
        source_statuses = {item.status for item in job.sources}
        if source_statuses and source_statuses.issubset({'success'}):
            job.status = 'completed'
        elif 'error' in source_statuses:
            job.status = 'completed_with_errors'
        else:
            job.status = 'processing'

    db.session.commit()
    return jsonify(source.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/simulate', methods=['POST'])
def simulate_extraction(job_id: int):
    job = Proceso1Job.query.get_or_404(job_id)

    for source in job.sources:
        source.status = 'success'
        source.extracted_content = 'Contenido extraído exitosamente (simulado desde backend Flask).'

    job.status = 'completed'
    db.session.commit()
    return jsonify(job.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/<subprocess_key>', methods=['GET'])
def get_subprocess_state(job_id: int, subprocess_key: str):
    Proceso1Job.query.get_or_404(job_id)
    state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key=subprocess_key).first()
    if state is None:
        return jsonify({
            'jobId': job_id,
            'subprocessKey': subprocess_key,
            'status': 'draft',
            'input': {},
            'output': {},
            'metadata': {},
        })
    return jsonify(state.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/<subprocess_key>', methods=['PUT'])
def upsert_subprocess_state(job_id: int, subprocess_key: str):
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key=subprocess_key).first()
    if state is None:
        state = Proceso1SubprocessState(job_id=job_id, subprocess_key=subprocess_key)
        db.session.add(state)

    if 'status' in payload and payload.get('status') is not None:
        state.status = str(payload.get('status'))

    if 'input' in payload:
        state.input_payload = payload.get('input') or {}

    if 'output' in payload:
        state.output_payload = payload.get('output') or {}

    if 'metadata' in payload:
        state.metadata_payload = payload.get('metadata') or {}

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 1 — Generate Strategic Analysis Prompt
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso1/run', methods=['POST'])
def run_subproceso1(job_id: int):
    """Generate the strategic analysis prompt using local templates."""
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    # SP1 is analysis-only. Final structure choices belong to SP2.
    prompt_mode = 'freedom'

    # Get selectedTitle: from payload (explicit override) or from the Job model (set by Proceso 0)
    selected_title = str(payload.get('selectedTitle') or '').strip() or _get_selected_title(job_id)

    # Fetch sources and prepare the input
    bundle = build_source_bundle(
        job,
        ensure_extracted=False,
        use_legacy_fallback=False,
        fallback_to_url=False,
    )
    aggregated_data = [
        {
            "titulo": item['title'],
            "texto": item['text'],
            "tipo": item['type'],
        }
        for item in bundle['items']
    ]
        
    try:
        from .prompts.strategic_analysis import generate_strategic_analysis_prompt
        
        if len(aggregated_data) > 0:
            main_video_data = aggregated_data[0]
            supplementary_data = aggregated_data[1:]
        else:
            main_video_data = {}
            supplementary_data = []
            
        result = generate_strategic_analysis_prompt(
            main_video_data, supplementary_data,
            prompt_mode=prompt_mode, selected_title=selected_title,
        )
    except Exception as exc:
        return jsonify({'error': f'Error generating strategic analysis prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso1')
    state.status = 'completed'
    state.output_payload = {
        'strategicAnalysisPrompt': result.get('prompt_completo', ''),
        'strategicAnalysisPromptOptimizado': result.get('prompt_optimizado', ''),
        'promptMode': prompt_mode,
        'selectedTitle': selected_title,
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 2 — Segmentation: Run (Gemini Flash)
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso2/segment/run', methods=['POST'])
def run_subproceso2_segment(job_id: int):
    """Run auto-segmentation of deepResearchOutput and infoInternaOutput by subtema using Gemini Flash.
    This is done as part of SP2 so segmented data is available before SP4."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    deep_research_output = str(payload.get('deepResearchOutput') or '').strip()
    info_interna_output = str(payload.get('infoInternaOutput') or '').strip()

    if not deep_research_output:
        return jsonify({'error': 'deepResearchOutput is required'}), 400
    if not info_interna_output:
        return jsonify({'error': 'infoInternaOutput is required'}), 400

    # Get estructura from SP2
    sp2_state = Proceso1SubprocessState.query.filter_by(
        job_id=job_id, subprocess_key='subproceso2'
    ).first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']
    subtemas = estructura.get('subtemas', [])
    if not subtemas:
        return jsonify({'error': 'No subtemas found in estructura'}), 400

    # Get Gemini API config
    from flask import current_app
    api_key = current_app.config.get('GEMINI_API_KEY', '')
    model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
    if not api_key:
        try:
            from config import GEMINI_API_KEY, GEMINI_MODEL
            api_key = GEMINI_API_KEY
            model_name = GEMINI_MODEL
        except ImportError:
            pass
    if not api_key:
        return jsonify({'error': 'GEMINI_API_KEY not configured'}), 500

    try:
        import importlib, pathlib
        _seg_path = pathlib.Path(__file__).parent / 'core' / 'segmentador.py'
        _spec = importlib.util.spec_from_file_location('segmentador', _seg_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        segment_info_by_subtemas = _mod.segment_info_by_subtemas
        results = segment_info_by_subtemas(
            api_key=api_key,
            model_name=model_name,
            subtemas=subtemas,
            info_externa=deep_research_output,
            info_interna=info_interna_output,
            parallel=2,
            wait_seconds=60,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Segmentation failed: {exc}'}), 500

    # Save as pending_approval in a dedicated state
    seg_state = get_or_create_subprocess_state(job_id, 'subproceso2_segmentation')
    seg_state.status = 'pending_approval'
    seg_state.input_payload = {
        'deepResearchOutput': deep_research_output,
        'infoInternaOutput': info_interna_output,
    }
    seg_state.output_payload = {
        'segmented': results,
        'subtemaCount': len(subtemas),
        'segmentedKeys': list(results.keys()),
    }

    db.session.commit()
    return jsonify({
        'status': 'pending_approval',
        'segmented': results,
        'subtemaCount': len(subtemas),
    })


# ---------------------------------------------------------------------------
# Subproceso 2 — Segmentation: Approve
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso2/segment/approve', methods=['POST'])
def approve_subproceso2_segment(job_id: int):
    """Approve (and optionally edit) the segmentation done in SP2.
    Copies approved data into each subproceso4_subtemaX input state."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    # Load existing segmentation state
    seg_state = Proceso1SubprocessState.query.filter_by(
        job_id=job_id, subprocess_key='subproceso2_segmentation'
    ).first()
    if not seg_state or not seg_state.output_payload or not seg_state.output_payload.get('segmented'):
        return jsonify({'error': 'No segmentation found. Run segmentation first.'}), 400

    # Allow optional edits: client can send edited segments
    edited_segments = payload.get('editedSegments')
    segmented = edited_segments if edited_segments else seg_state.output_payload['segmented']

    # Update segmentation state to approved
    if edited_segments:
        seg_state.output_payload = {
            **seg_state.output_payload,
            'segmented': segmented,
        }
    seg_state.status = 'approved'

    # Copy segmented data into each SP4 subtema state
    sp2_state = Proceso1SubprocessState.query.filter_by(
        job_id=job_id, subprocess_key='subproceso2'
    ).first()
    subtemas = []
    if sp2_state and sp2_state.output_payload:
        estructura = sp2_state.output_payload.get('estructura', {})
        subtemas = estructura.get('subtemas', [])

    for i, _subtema in enumerate(subtemas):
        key = f"subtema_{i + 1}"
        seg = segmented.get(key, {})
        sp4_key = f"subproceso4_subtema{i + 1}"
        state = get_or_create_subprocess_state(job_id, sp4_key)
        existing_input = state.input_payload or {}
        state.input_payload = {
            **existing_input,
            'infoExterna': seg.get('infoExterna', ''),
            'infoInterna': seg.get('infoInterna', ''),
            'autoSegmented': True,
            'segmentedFromSP2': True,
        }

    db.session.commit()
    return jsonify({
        'status': 'approved',
        'segmented': segmented,
        'subtemaCount': len(subtemas),
    })


# ---------------------------------------------------------------------------
# Subproceso 3 — Generate Introduction Prompt
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso3/run', methods=['POST'])
def run_subproceso3(job_id: int):
    """Generate the introduction prompt (Round 1) using local prompt templates."""
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    keyword = str(payload.get('keyword') or '').strip()
    deep_research_output = str(payload.get('deepResearchOutput') or '').strip()
    info_interna_output = str(payload.get('infoInternaOutput') or '').strip()

    # Accept prompt_mode: "solid" (default, rigid formula) or "freedom" (guided creative freedom)
    prompt_mode = str(payload.get('promptMode') or 'solid').strip()
    if prompt_mode not in ('solid', 'freedom'):
        prompt_mode = 'solid'

    if not keyword:
        return jsonify({'error': 'keyword is required'}), 400
    if not deep_research_output:
        return jsonify({'error': 'deepResearchOutput is required'}), 400
    if not info_interna_output:
        return jsonify({'error': 'infoInternaOutput is required'}), 400

    # Load estructura from subproceso2 output
    sp2_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso2').first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']

    # Retrieve the selected title (North Star) from SP1/SP2
    selected_title = _get_selected_title(job_id)

    try:
        from .prompts.introduccion import generate_intro_prompt
        result = generate_intro_prompt(
            estructura, deep_research_output, info_interna_output,
            keyword, selected_title=selected_title,
            prompt_mode=prompt_mode,
        )
    except Exception as exc:
        return jsonify({'error': f'Error generating intro prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso3')
    state.status = 'completed'
    state.input_payload = {
        'keyword': keyword,
        'deepResearchOutput': deep_research_output,
        'infoInternaOutput': info_interna_output,
    }
    state.output_payload = {
        'introPrompt': result.get('prompt_completo', ''),
        'introPromptOptimizado': result.get('prompt_optimizado', ''),
        'promptMode': prompt_mode,
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Auto-Segmentation — Segment info by subtemas using Gemini Flash
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/auto-segment/run', methods=['POST'])
def run_auto_segment(job_id: int):
    """Auto-segment info_externa and info_interna by subtema using Gemini Flash."""
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    # Get the full info blocks — either from payload or from SP3 saved input
    info_externa = str(payload.get('infoExterna') or '').strip()
    info_interna = str(payload.get('infoInterna') or '').strip()

    if not info_externa or not info_interna:
        sp3_state = Proceso1SubprocessState.query.filter_by(
            job_id=job_id, subprocess_key='subproceso3'
        ).first()
        if sp3_state and sp3_state.input_payload:
            if not info_externa:
                info_externa = str(sp3_state.input_payload.get('deepResearchOutput') or '').strip()
            if not info_interna:
                info_interna = str(sp3_state.input_payload.get('infoInternaOutput') or '').strip()

    if not info_externa:
        return jsonify({'error': 'infoExterna is required (or complete SP3 first)'}), 400
    if not info_interna:
        return jsonify({'error': 'infoInterna is required (or complete SP3 first)'}), 400

    # Get estructura from SP2
    sp2_state = Proceso1SubprocessState.query.filter_by(
        job_id=job_id, subprocess_key='subproceso2'
    ).first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']
    subtemas = estructura.get('subtemas', [])
    if not subtemas:
        return jsonify({'error': 'No subtemas found in estructura'}), 400

    # Get Gemini API config
    api_key = current_app.config.get('GEMINI_API_KEY', '')
    model_name = current_app.config.get('GEMINI_MODEL', 'gemini-2.0-flash')
    if not api_key:
        try:
            from config import GEMINI_API_KEY, GEMINI_MODEL
            api_key = GEMINI_API_KEY
            model_name = GEMINI_MODEL
        except ImportError:
            pass
    if not api_key:
        return jsonify({'error': 'GEMINI_API_KEY not configured'}), 500

    try:
        from .core.segmentador import segment_info_by_subtemas
        results = segment_info_by_subtemas(
            api_key=api_key,
            model_name=model_name,
            subtemas=subtemas,
            info_externa=info_externa,
            info_interna=info_interna,
            parallel=2,
            wait_seconds=60,
        )
    except Exception as exc:
        return jsonify({'error': f'Segmentation failed: {exc}'}), 500

    # Save segmented data into each subtema's SP4 input state
    for i, subtema in enumerate(subtemas):
        key = f"subtema_{i + 1}"
        seg = results.get(key, {})
        sp4_key = f"subproceso4_subtema{i + 1}"
        state = get_or_create_subprocess_state(job_id, sp4_key)
        # Merge with existing input (don't overwrite saved scripts)
        existing_input = state.input_payload or {}
        state.input_payload = {
            **existing_input,
            'infoExterna': seg.get('infoExterna', ''),
            'infoInterna': seg.get('infoInterna', ''),
            'autoSegmented': True,
        }

    # Save a record of the segmentation
    seg_state = get_or_create_subprocess_state(job_id, 'auto_segment')
    seg_state.status = 'completed'
    seg_state.output_payload = {
        'subtemaCount': len(subtemas),
        'segmentedKeys': list(results.keys()),
    }

    db.session.commit()
    return jsonify({
        'status': 'completed',
        'segmented': results,
        'subtemaCount': len(subtemas),
    })


# ---------------------------------------------------------------------------
# Subproceso 3 Ensamblaje — Generate Assembly Prompt (Round 2)
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso3_ensamblaje/run', methods=['POST'])
def run_subproceso3_ensamblaje(job_id: int):
    """Generate the introduction-assembly prompt (Round 2)."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    gancho = str(payload.get('gancho') or '').strip()
    pregunta = str(payload.get('pregunta') or '').strip()
    peso = str(payload.get('peso') or '').strip()
    indice = str(payload.get('indice') or '').strip()
    puerta = str(payload.get('puerta') or '').strip()

    if not gancho:
        return jsonify({'error': 'gancho is required'}), 400
    if not pregunta:
        return jsonify({'error': 'pregunta is required'}), 400

    try:
        from .prompts.introduccion_ensamblaje import generate_ensamblaje_prompt
        result = generate_ensamblaje_prompt(gancho, pregunta, peso, indice, puerta)
    except Exception as exc:
        return jsonify({'error': f'Error generating ensamblaje prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso3_ensamblaje')
    state.status = 'completed'
    state.input_payload = {
        'gancho': gancho,
        'pregunta': pregunta,
        'peso': peso,
        'indice': indice,
        'puerta': puerta,
    }
    state.output_payload = {
        'ensamblajePrompt': result.get('prompt_completo', ''),
        'ensamblajePromptOptimizado': result.get('prompt_optimizado', ''),
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 3 Índice Rápido — Generate the 10-second Rapid Index Prompt
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso3_indice/run', methods=['POST'])
def run_subproceso3_indice(job_id: int):
    """Generate the Rapid Index prompt (~10 seconds) that bridges the cinematic intro and SP4.
    Accepts an optional introCinematica in the body so the text is persisted to the DB
    and can be restored if the user navigates away and comes back."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}
    intro_cinematica = str(payload.get('introCinematica') or '').strip()

    # Load estructura from subproceso2 output
    sp2_state = Proceso1SubprocessState.query.filter_by(
        job_id=job_id, subprocess_key='subproceso2'
    ).first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']

    try:
        from .prompts.indice_rapido import generate_indice_rapido_prompt
        result = generate_indice_rapido_prompt(estructura)
    except Exception as exc:
        return jsonify({'error': f'Error generating indice rapido prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso3_indice')
    state.status = 'prompt_ready'
    # Persist the pasted intro so it can be restored on page reload
    existing_input = state.input_payload or {}
    state.input_payload = {
        **existing_input,
        'introCinematica': intro_cinematica,
    }
    state.output_payload = {
        'indicePrompt': result.get('prompt_completo', ''),
        'indicePromptOptimizado': result.get('prompt_optimizado', ''),
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 3 Índice Rápido — Save the assembled full intro
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso3_indice/save', methods=['POST'])
def save_subproceso3_indice(job_id: int):
    """Receive the rapid index text pasted by the user, concatenate it with the
    cinematic intro already stored in subproceso3's input, and persist introCompleta
    back into subproceso3's output_payload (no new DB columns needed)."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    intro_cinematica = str(payload.get('introCinematica') or '').strip()
    indice_rapido = str(payload.get('indiceRapido') or '').strip()

    if not intro_cinematica:
        return jsonify({'error': 'introCinematica is required'}), 400
    if not indice_rapido:
        return jsonify({'error': 'indiceRapido is required'}), 400

    intro_completa = f"{intro_cinematica}\n\n{indice_rapido}"

    # Save indice result and introCompleta into subproceso3_indice state
    state = get_or_create_subprocess_state(job_id, 'subproceso3_indice')
    existing_output = state.output_payload or {}
    state.status = 'completed'
    state.input_payload = {
        'introCinematica': intro_cinematica,
        'indiceRapido': indice_rapido,
    }
    state.output_payload = {
        **existing_output,
        'indiceRapido': indice_rapido,
        'introCompleta': intro_completa,
    }

    # Also update subproceso3 output so the intro is accessible from there
    sp3_state = get_or_create_subprocess_state(job_id, 'subproceso3')
    sp3_output = sp3_state.output_payload or {}
    sp3_state.output_payload = {
        **sp3_output,
        'introCompleta': intro_completa,
        'introCinematica': intro_cinematica,
    }

    db.session.commit()
    return jsonify({
        'status': 'completed',
        'introCompleta': intro_completa,
    })



@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso4/run', methods=['POST'])
def run_subproceso4(job_id: int):
    """Generate prompt for a single subtema body section."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    subtema_index = int(payload.get('subtemaIndex', 0))
    info_externa = str(payload.get('infoExterna') or '').strip()
    info_interna = str(payload.get('infoInterna') or '').strip()
    script_acumulado = str(payload.get('scriptAcumulado') or '').strip()

    # Load estructura first to know how many subtemas we have
    sp2_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso2').first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']
    subtemas = estructura.get('subtemas', [])
    max_subtemas = len(subtemas)

    if subtema_index < 1 or subtema_index > max_subtemas:
        return jsonify({'error': f'subtemaIndex must be 1-{max_subtemas}'}), 400
    if not info_externa:
        return jsonify({'error': 'infoExterna is required'}), 400
    if not info_interna:
        return jsonify({'error': 'infoInterna is required'}), 400



    subtema_actual = subtemas[subtema_index - 1]
    subtema_siguiente = subtemas[subtema_index] if subtema_index < len(subtemas) else None
    keyword_principal = estructura.get('keyword_principal') or estructura.get('tema_principal', '')

    # Retrieve the selected title (North Star) from SP1/SP2
    selected_title = _get_selected_title(job_id)

    try:
        from .prompts.cuerpo_subtema import generate_cuerpo_subtema_prompt
        result = generate_cuerpo_subtema_prompt(
            subtema_actual=subtema_actual,
            subtema_siguiente=subtema_siguiente,
            info_externa=info_externa,
            info_interna=info_interna,
            script_acumulado=script_acumulado,
            keyword_principal=keyword_principal,
            estructura=estructura,
            numero_subtema=subtema_index,
            selected_title=selected_title,
        )
    except Exception as exc:
        return jsonify({'error': f'Error generating cuerpo prompt: {exc}'}), 500

    state_key = f'subproceso4_subtema{subtema_index}'
    state = get_or_create_subprocess_state(job_id, state_key)
    state.status = 'completed'
    state.input_payload = {
        'subtemaIndex': subtema_index,
        'infoExterna': info_externa,
        'infoInterna': info_interna,
        'scriptAcumulado': script_acumulado,
    }
    state.output_payload = {
        'cuerpoPrompt': result.get('prompt_completo', ''),
        'cuerpoPromptOptimizado': result.get('prompt_optimizado', ''),
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 4 — Save script for a subtema
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso4/save-script', methods=['POST'])
def save_subproceso4_script(job_id: int):
    """Save the generated script for a specific subtema."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    subtema_index = int(payload.get('subtemaIndex', 0))
    script = str(payload.get('script') or '').strip()

    if subtema_index < 1:
        return jsonify({'error': 'subtemaIndex must be >= 1'}), 400

    state_key = f'subproceso4_subtema{subtema_index}'
    state = get_or_create_subprocess_state(job_id, state_key)
    existing_input = state.input_payload or {}
    existing_output = state.output_payload or {}

    state.status = 'completed'
    state.input_payload = {**existing_input, 'script': script}
    state.output_payload = existing_output

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 4 — Save intro final
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso4_intro/save', methods=['POST'])
def save_subproceso4_intro(job_id: int):
    """Save the final intro text that will be used as the start of the accumulated script."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    intro_final = str(payload.get('introFinal') or '').strip()

    state = get_or_create_subprocess_state(job_id, 'subproceso4_intro')
    state.status = 'saved'
    state.input_payload = {'introFinal': intro_final}

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 5 — Generate Closing Prompt
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso5/run', methods=['POST'])
def run_subproceso5(job_id: int):
    """Generate the closing prompt for the video."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    script_completo = str(payload.get('scriptCompleto') or '').strip()
    if not script_completo:
        return jsonify({'error': 'scriptCompleto is required'}), 400

    # Load estructura from subproceso2
    sp2_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso2').first()
    if not sp2_state or not sp2_state.output_payload or not sp2_state.output_payload.get('estructura'):
        return jsonify({'error': 'Subproceso 2 must be completed first (estructura missing)'}), 400

    estructura = sp2_state.output_payload['estructura']
    keyword_principal = estructura.get('keyword_principal') or estructura.get('tema_principal', '')

    # Retrieve the selected title (North Star) from SP1/SP2
    selected_title = _get_selected_title(job_id)

    try:
        from .prompts.cierre_video import generate_cierre_prompt
        result = generate_cierre_prompt(
            script_completo, keyword_principal, estructura,
            selected_title=selected_title,
        )
    except Exception as exc:
        return jsonify({'error': f'Error generating cierre prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso5')
    state.status = 'completed'
    state.input_payload = {
        'scriptCompleto': script_completo,
    }
    state.output_payload = {
        'cierrePrompt': result.get('prompt_completo', ''),
        'cierrePromptOptimizado': result.get('prompt_optimizado', ''),
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 5 — Save closing script + assemble script final
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso5/save-final', methods=['POST'])
def save_subproceso5_final(job_id: int):
    """Save closing script and assemble the final complete script."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    cierre_script = str(payload.get('cierreScript') or '').strip()

    # Assemble script: intro + 4 subtemas + cierre
    parts = []

    # 1. Intro
    intro_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso4_intro').first()
    if intro_state and intro_state.input_payload:
        intro_text = intro_state.input_payload.get('introFinal', '')
        if intro_text:
            parts.append(f"=== INTRODUCCIÓN ===\n{intro_text}")

    # 2. Subtemas (dynamic — supports any number of subtemas)
    for i in range(1, 20):  # Check up to 20 subtemas (more than enough)
        st = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key=f'subproceso4_subtema{i}').first()
        if st and st.input_payload:
            script = st.input_payload.get('script', '')
            if script:
                parts.append(f"=== PARTE {i} ===\n{script}")
        elif i > 4:
            # Stop searching once we pass the default 4 and find nothing
            break

    # 3. Cierre
    if cierre_script:
        parts.append(f"=== CIERRE ===\n{cierre_script}")

    script_final = "\n\n".join(parts)

    # Word count stats
    word_count = len(script_final.split()) if script_final else 0
    estimated_minutes = round(word_count / 150, 1)  # ~150 WPM reading speed

    state = get_or_create_subprocess_state(job_id, 'subproceso5_final')
    state.status = 'completed'
    state.input_payload = {'cierreScript': cierre_script}
    state.output_payload = {
        'scriptFinal': script_final,
        'stats': {
            'wordCount': word_count,
            'estimatedMinutes': estimated_minutes,
            'charCount': len(script_final),
        },
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 6 — Generate Master Editor Prompt
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso6/run', methods=['POST'])
def run_subproceso6(job_id: int):
    """Generate the master editor prompt using the assembled script final from SP5."""
    Proceso1Job.query.get_or_404(job_id)

    # Load script final from subproceso5_final
    sp5_final_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso5_final').first()
    if not sp5_final_state or not sp5_final_state.output_payload or not sp5_final_state.output_payload.get('scriptFinal'):
        return jsonify({'error': 'Subproceso 5 must be completed first (scriptFinal missing)'}), 400

    guion_crudo = str(sp5_final_state.output_payload['scriptFinal']).strip()

    # Retrieve the selected title (North Star) from SP1/SP2
    selected_title = _get_selected_title(job_id)

    try:
        from .prompts.edicion_maestra import generate_edicion_maestra_prompt
        result = generate_edicion_maestra_prompt(guion_crudo, selected_title=selected_title)
    except Exception as exc:
        return jsonify({'error': f'Error generating edicion maestra prompt: {exc}'}), 500

    state = get_or_create_subprocess_state(job_id, 'subproceso6')
    state.status = 'completed'
    state.input_payload = {
        'guionCrudo': guion_crudo,
    }
    state.output_payload = {
        'edicionMaestraPrompt': result.get('prompt_completo', ''),
        'edicionMaestraPromptOptimizado': result.get('prompt_optimizado', ''),
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 6 — Save the final edited script
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso6/save-final', methods=['POST'])
def save_subproceso6_final(job_id: int):
    """Save the AI-edited final script split by segments (intro, parte1-4, cierre)."""
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    SEGMENT_KEYS = ['intro'] + [f'parte{i}' for i in range(1, 9)] + ['cierre']  # supports up to 8 parts

    # Accept either segmented payload OR legacy single scriptEditado string
    segments: dict = {}
    if any(k in payload for k in SEGMENT_KEYS):
        # New segmented flow
        for k in SEGMENT_KEYS:
            segments[k] = str(payload.get(k) or '').strip()
    elif payload.get('scriptEditado'):
        # Legacy fallback: single string (kept for backwards compat)
        segments = {'intro': '', 'parte1': '', 'parte2': '', 'parte3': '', 'parte4': '', 'cierre': ''}
        segments['intro'] = str(payload.get('scriptEditado') or '').strip()
    else:
        return jsonify({'error': 'Se requiere al menos un segmento (intro, parte1..parte4, cierre) o scriptEditado'}), 400

    # Build full assembled script for stats
    ordered = [segments.get(k, '') for k in SEGMENT_KEYS]
    script_completo = '\n\n'.join(p for p in ordered if p)

    word_count = len(script_completo.split()) if script_completo else 0
    estimated_minutes = round(word_count / 150, 1)

    # Per-segment stats
    seg_stats = {}
    for k in SEGMENT_KEYS:
        txt = segments.get(k, '')
        wc = len(txt.split()) if txt else 0
        seg_stats[k] = {
            'wordCount': wc,
            'estimatedSeconds': round((wc / 150) * 60),
        }

    state = get_or_create_subprocess_state(job_id, 'subproceso6_final')
    state.status = 'completed'
    state.input_payload = {**segments}  # store each segment individually
    state.output_payload = {
        'scriptEditado': script_completo,   # full assembled (legacy compat)
        'segments': segments,               # keyed by segment
        'segmentStats': seg_stats,
        'stats': {
            'wordCount': word_count,
            'estimatedMinutes': estimated_minutes,
            'charCount': len(script_completo),
        },
    }

    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Subproceso 6 — Generate Reduction Prompt for a specific segment
# ---------------------------------------------------------------------------

@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso6/reduccion-prompt', methods=['POST'])
def generate_reduccion_prompt(job_id: int):
    """
    Generates a reduction prompt for a single script segment.
    The Proceso 2 frontend calls this when a segment's audio is too long.
    """
    Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    segment_key = str(payload.get('segmentKey') or '').strip()
    bruto_seconds = float(payload.get('brutoSeconds') or 0)
    target_seconds = float(payload.get('targetSeconds') or 0)

    VALID_KEYS = ['intro'] + [f'parte{i}' for i in range(1, 9)] + ['cierre']
    if segment_key not in VALID_KEYS:
        return jsonify({'error': f'segmentKey debe ser uno de: {", ".join(VALID_KEYS)}'}), 400

    # Load the saved segments from subproceso6_final
    sp6_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso6_final').first()
    if not sp6_state:
        return jsonify({'error': 'Primero guarda el script editado en Subproceso 6'}), 400

    # Prefer segments dict, fallback to scriptEditado for legacy
    segments = (sp6_state.output_payload or {}).get('segments') or {}
    segment_text = str(segments.get(segment_key) or (sp6_state.input_payload or {}).get(segment_key) or '').strip()

    if not segment_text:
        return jsonify({'error': f'No hay texto guardado para el segmento "{segment_key}"'}), 400

    # Calculate reduction percentage
    reduction_pct = 0
    if bruto_seconds > 0 and target_seconds > 0 and bruto_seconds > target_seconds:
        reduction_pct = round(((bruto_seconds - target_seconds) / bruto_seconds) * 100)
    elif target_seconds > 0:
        # Even if not over target, calculate a default 10% reduction goal so the
        # prompt always has a meaningful target when used proactively.
        reduction_pct = 10

    seg_label_map = {
        'intro': 'Introducción', 'parte1': 'Parte 1', 'parte2': 'Parte 2',
        'parte3': 'Parte 3', 'parte4': 'Parte 4', 'cierre': 'Cierre'
    }
    seg_label = seg_label_map.get(segment_key, segment_key)

    # Transition guard — every segment except Cierre has a transition to the next block
    last_sentence_rule = (
        "- TRANSITION LOCK: The LAST sentence (or last two sentences) of this section "
        "is the narrative bridge into the next block. It MUST remain EXACTLY as written. "
        "Do NOT delete, paraphrase, or shorten it under any circumstance.\n"
        if segment_key != 'cierre' else ""
    )

    prompt = f"""ROLE: Master YouTube Script Editor & Retention Surgeon.

YOUR CONTEXT: You edit long-form YouTube videos that ALWAYS follow a strict 6-part structure:
1. Introducción (Hook & Index)
2. Parte 1 (Building the foundation, high viewer patience, atmospheric)
3. Parte 2 (Deepening the rabbit hole)
4. Parte 3 (Peak complexity)
5. Parte 4 (Climax: Viewer patience is extremely low. Pacing must be ruthless and direct)
6. Cierre (Quick resolution and outro)

YOUR OBJECTIVE: Reduce the length of ONE specific section of the script by eliminating "fluff" \
(unnecessary words, secondary examples, redundant explanations) WITHOUT rewriting the core essence, \
the tone, or the pacing of the original text.

INPUT DATA:

REDUCTION TARGET: {reduction_pct}%
CURRENT SECTION TO TRIM: {seg_label}
RAW TEXT TO TRIM:
[START RAW TEXT]
{segment_text}
[END RAW TEXT]

YOUR SURGICAL RULES (STRICT STRICT STRICT):

1. THE GOLDEN RULE (DO NOT REWRITE): You are a surgeon, not an author. DO NOT paraphrase the entire \
text. You are only allowed to DELETE sentences or portions of sentences. The sentences you decide to \
keep MUST remain exactly as originally written.

2. ADAPT TO THE SECTION: Look at the "CURRENT SECTION TO TRIM". If it's early (e.g., Parte 1), \
preserve atmospheric descriptions. If it's late (e.g., Parte 4 or Cierre), be ruthless — cut anything \
that delays the climax.

3. WHAT TO CUT: Eliminate redundant transitions, secondary analogies, overlapping adjectives, or \
over-explained concepts. If a concept is already clear, cut the extra explanation.

4. INVISIBLE SUTURES (PATCHING): When you delete a sentence from the middle, you are allowed to add \
a MAXIMUM of 1 to 4 connecting words (like "Por lo tanto,", "Pero,", "Y así,") to connect the \
remaining sentences logically so there is no awkward jump or void.

5. THE UNTOUCHABLES: NEVER delete rhetorical questions, or the exact "punchlines" / shocking \
revelations highlighted in bold.
{last_sentence_rule}
6. DYNAMIC PACING & PUNCTUATION (TTS AWARENESS): When you delete text, the remaining punchy sentences \
might end up too close together. You must handle punctuation based strictly on the "CURRENT SECTION TO TRIM":
   - If it's Parte 1 or Parte 2: DO NOT touch the punctuation. Preserve EVERY period (.), double \
paragraph break, and ellipsis (...). These sections require slow, atmospheric breathing and dramatic pauses.
   - If it's Parte 3, Parte 4, or Cierre (The Climax): The pacing must accelerate wildly. ONLY HERE, \
if your cuts create a cluster of non-stop periods or ellipses, you must smooth them. Convert heavy \
stops (.) into commas (,) or fluid connectors ("and") so the Text-to-Speech Engine reads the climax \
rapidly, like a breathless revelation.

OUTPUT FORMAT:
You must return your response in two clear sections.

1. REGISTRO DE CAMBIOS (CHANGELOG)
List exactly what you modified so the Director can validate the cuts. Use this format:

❌ Eliminado: "[Exact sentence or phrase you removed]"
🩹 Parche usado: "[The 1-4 words you added to bridge the gap, or 'Ninguno']"
💡 Razón: "[Brief logic based on the Section's pacing rules]"

2. TEXTO DE PODA FINAL (FINAL TRIMMED TEXT)
[Provide the final stitched text here, maintaining all original formatting like ellipses, paragraph \
breaks, and bolded words. Ready to be used for TTS synthesis.]"""

    return jsonify({
        'segmentKey': segment_key,
        'segmentLabel': seg_label,
        'brutoSeconds': bruto_seconds,
        'targetSeconds': target_seconds,
        'reductionPct': reduction_pct,
        'originalText': segment_text,
        'reduccionPrompt': prompt,
    })


@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso2/run', methods=['POST'])
def run_subproceso2(job_id: int):
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    state = get_or_create_subprocess_state(job_id, 'subproceso2')
    existing_input = state.input_payload or {}

    analysis_text = str(payload.get('analysisText') or existing_input.get('strategicAnalysis') or '').strip()
    if not analysis_text:
        return jsonify({'error': 'analysisText is required'}), 400

    # Resolve prompt_mode: from payload, or from SP1 output, or default "solid"
    sp1_state = Proceso1SubprocessState.query.filter_by(job_id=job_id, subprocess_key='subproceso1').first()
    sp1_prompt_mode = (sp1_state.output_payload or {}).get('promptMode', 'solid') if sp1_state else 'solid'
    prompt_mode = resolve_prompt_mode(payload.get('promptMode'), fallback_mode=sp1_prompt_mode, allow_hybrid=True)

    bundle = build_source_bundle(job, ensure_extracted=True, use_legacy_fallback=True)
    sources = bundle['sources']
    if not sources:
        return jsonify({'error': 'No sources found for this project'}), 400
    datos_crudos_texto = bundle['raw_text']

    # Retrieve selected title from SP1 output or payload
    selected_title = str(payload.get('selectedTitle') or '').strip()
    if not selected_title:
        selected_title = _get_selected_title(job_id)

    try:
        stage_result = run_story_structure_stage(
            analysis_text=analysis_text,
            raw_sources_text=datos_crudos_texto,
            prompt_mode=prompt_mode,
            selected_title=selected_title,
            project_external_id=str(job.video_id),
        )
    except Exception as exc:
        return jsonify({'error': f'Error running subproceso2: {exc}'}), 500

    state.input_payload = {
        **existing_input,
        'strategicAnalysis': analysis_text,
        'promptMode': prompt_mode,
    }
    state.metadata_payload = {
        'sourceCount': bundle['source_count'],
        'jobStatus': job.status,
    }
    state.status = stage_result['status']
    state.output_payload = stage_result['output']

    db.session.commit()
    return jsonify(state.to_dict())


@proceso1_bp.route('/jobs/<int:job_id>/subprocesses/subproceso2/condense/run', methods=['POST'])
def run_subproceso2_condense(job_id: int):
    """
    Finaliza el modo híbrido manual.
    Recibe el JSON pegado desde ChatGPT con:
    - estructura_libre
    - estructura_final
    Lo valida, lo normaliza y genera los prompts de Deep Research e Info Interna.
    """
    job = Proceso1Job.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    hybrid_output_text = str(
        payload.get('hybridOutputText')
        or payload.get('condensedAnalysisText')
        or ''
    ).strip()
    if not hybrid_output_text:
        return jsonify({'error': 'hybridOutputText is required'}), 400

    state = get_or_create_subprocess_state(job_id, 'subproceso2')
    existing_input = state.input_payload or {}
    existing_output = state.output_payload or {}

    # Build datos_crudos from sources (needed for step2_generar_prompts)
    bundle = build_source_bundle(job, ensure_extracted=False, use_legacy_fallback=True)
    sources = bundle['sources']
    if not sources:
        return jsonify({'error': 'No sources found for this project'}), 400
    datos_crudos_texto = bundle['raw_text']

    selected_title = _get_selected_title(job_id)

    try:
        stage_result = complete_hybrid_story_structure(
            hybrid_output_text=hybrid_output_text,
            raw_sources_text=datos_crudos_texto,
            selected_title=selected_title,
            existing_output=existing_output,
        )
    except Exception as exc:
        return jsonify({'error': f'Error running subproceso2 condense: {exc}'}), 500

    state.input_payload = {
        **existing_input,
        'hybridOutputText': hybrid_output_text,
    }
    state.status = stage_result['status']
    state.output_payload = stage_result['output']

    db.session.commit()
    return jsonify(state.to_dict())
