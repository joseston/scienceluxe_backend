from flask import Blueprint, jsonify, request

from aplicacion import db
from aplicacion.models.proceso1_corto import (
    Proceso1CortoJob,
    Proceso1CortoSubprocessState,
)


proceso1_corto_bp = Blueprint('proceso1_corto', __name__)


def get_or_create_subprocess_state(job_id: int, subprocess_key: str) -> Proceso1CortoSubprocessState:
    state = Proceso1CortoSubprocessState.query.filter_by(job_id=job_id, subprocess_key=subprocess_key).first()
    if state is None:
        state = Proceso1CortoSubprocessState(job_id=job_id, subprocess_key=subprocess_key)
        db.session.add(state)
    return state


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/quick', methods=['POST'])
def quick_create_job():
    """Create a minimal Proceso1CortoJob without going through script steps.
    Used when the user already has a script/audio and wants to jump to Proceso2+."""
    payload = request.get_json(silent=True) or {}
    title = (payload.get('title') or payload.get('mainIdea') or 'Proyecto sin script').strip()

    job = Proceso1CortoJob(video_id=title, status='bypassed')
    db.session.add(job)
    db.session.commit()

    return jsonify(job.to_dict()), 201


@proceso1_corto_bp.route('/jobs', methods=['POST'])
def create_job():
    """Create a new short video job with just a mainIdea."""
    payload = request.get_json(silent=True) or {}
    main_idea = (payload.get('mainIdea') or '').strip()

    if not main_idea:
        return jsonify({'error': 'mainIdea is required'}), 400

    job = Proceso1CortoJob(video_id=main_idea, status='created')
    db.session.add(job)
    db.session.commit()

    return jsonify(job.to_dict()), 201


@proceso1_corto_bp.route('/jobs', methods=['GET'])
def list_jobs():
    limit = request.args.get('limit', default=20, type=int)
    jobs = Proceso1CortoJob.query.order_by(Proceso1CortoJob.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return jsonify({'items': [job.to_dict() for job in jobs]})


@proceso1_corto_bp.route('/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id: int):
    job = Proceso1CortoJob.query.get_or_404(job_id)
    return jsonify(job.to_dict())


# ---------------------------------------------------------------------------
# Subprocess state endpoints
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/<int:job_id>/subprocesses/<subprocess_key>', methods=['GET'])
def get_subprocess_state(job_id: int, subprocess_key: str):
    Proceso1CortoJob.query.get_or_404(job_id)
    state = Proceso1CortoSubprocessState.query.filter_by(job_id=job_id, subprocess_key=subprocess_key).first()
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


# ---------------------------------------------------------------------------
# Step 1 — Generate Research Prompt
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/<int:job_id>/step1/run', methods=['POST'])
def run_step1(job_id: int):
    """Generate the research prompt from the main idea."""
    job = Proceso1CortoJob.query.get_or_404(job_id)
    main_idea = job.video_id  # video_id stores the main idea

    from .prompts.prompt1_research import generate_research_prompt
    prompt = generate_research_prompt(main_idea)

    state = get_or_create_subprocess_state(job_id, 'step1')
    state.status = 'completed'
    state.input_payload = {'mainIdea': main_idea}
    state.output_payload = {'researchPrompt': prompt}

    job.status = 'step1_completed'
    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Step 2 — Generate Introduction Prompt
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/<int:job_id>/step2/run', methods=['POST'])
def run_step2(job_id: int):
    """Generate 6 introduction alternatives prompt from main idea + research info."""
    job = Proceso1CortoJob.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    information = (payload.get('information') or '').strip()
    if not information:
        return jsonify({'error': 'information is required (paste the research results)'}), 400

    main_idea = job.video_id

    from .prompts.prompt2_introduction import generate_introduction_prompt
    prompt = generate_introduction_prompt(main_idea, information)

    state = get_or_create_subprocess_state(job_id, 'step2')
    state.status = 'completed'
    state.input_payload = {'information': information}
    state.output_payload = {'introductionPrompt': prompt}

    job.status = 'step2_completed'
    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Step 3 — Generate Final Script Prompt
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/<int:job_id>/step3/run', methods=['POST'])
def run_step3(job_id: int):
    """Generate the final script prompt from main idea + information + chosen introduction."""
    job = Proceso1CortoJob.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    introduction = (payload.get('introduction') or '').strip()
    if not introduction:
        return jsonify({'error': 'introduction is required'}), 400

    main_idea = job.video_id

    # Get information from step2
    step2_state = Proceso1CortoSubprocessState.query.filter_by(job_id=job_id, subprocess_key='step2').first()
    if not step2_state or not step2_state.input_payload:
        return jsonify({'error': 'Step 2 must be completed first'}), 400

    information = step2_state.input_payload.get('information', '')

    from .prompts.prompt3_script import generate_script_prompt
    prompt = generate_script_prompt(main_idea, information, introduction)

    state = get_or_create_subprocess_state(job_id, 'step3')
    state.status = 'completed'
    state.input_payload = {'introduction': introduction}
    state.output_payload = {'scriptPrompt': prompt}

    job.status = 'step3_completed'
    db.session.commit()
    return jsonify(state.to_dict())


# ---------------------------------------------------------------------------
# Step 3 — Save Final Script
# ---------------------------------------------------------------------------

@proceso1_corto_bp.route('/jobs/<int:job_id>/step3/save-final', methods=['POST'])
def save_final_script(job_id: int):
    """Save the final script the user got from ChatGPT/Gemini."""
    Proceso1CortoJob.query.get_or_404(job_id)
    payload = request.get_json(silent=True) or {}

    script_final = (payload.get('scriptFinal') or '').strip()
    if not script_final:
        return jsonify({'error': 'scriptFinal is required'}), 400

    word_count = len(script_final.split())
    estimated_seconds = round((word_count / 150) * 60)

    state = get_or_create_subprocess_state(job_id, 'final_script')
    state.status = 'completed'
    state.input_payload = {'scriptFinal': script_final}
    state.output_payload = {
        'scriptFinal': script_final,
        'stats': {
            'wordCount': word_count,
            'estimatedSeconds': estimated_seconds,
            'charCount': len(script_final),
        },
    }

    job = Proceso1CortoJob.query.get(job_id)
    if job:
        job.status = 'completed'
    db.session.commit()
    return jsonify(state.to_dict())
