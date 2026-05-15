from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from flask import Blueprint, jsonify, request

from aplicacion.models.proceso1 import Proceso1Job, Proceso1SubprocessState
from aplicacion.models.proceso1_corto import Proceso1CortoJob, Proceso1CortoSubprocessState
from aplicacion.models.proceso2 import Proceso2Job, Proceso2SubprocessState
from aplicacion.models.proceso2_corto import Proceso2CortoJob, Proceso2CortoSubprocessState
from aplicacion.models.proceso3 import Proceso3Job, Proceso3SubprocessState
from aplicacion.models.proceso3_corto import Proceso3CortoJob, Proceso3CortoSubprocessState
from aplicacion.models.proceso4 import Proceso4Job, Proceso4SceneMedia, Proceso4SubprocessState
from aplicacion.models.proceso4_corto import Proceso4CortoJob, Proceso4CortoSceneMedia, Proceso4CortoSubprocessState
from aplicacion.models.proceso5 import Proceso5Job, Proceso5SubprocessState


videos_bp = Blueprint("videos", __name__)

ERROR_STATUSES = {"error", "failed", "failure", "completed_with_errors"}
COMPLETED_STATUSES = {"completed", "success", "done", "finished"}
PENDING_STATUSES = {"", "draft", "created", "pending", "idle"}


def _drafts_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "proceso0"


def _load_proceso0_drafts() -> dict[int, dict]:
    drafts_by_job_id: dict[int, dict] = {}
    drafts_dir = _drafts_dir()
    if not drafts_dir.exists():
        return drafts_by_job_id

    for path in drafts_dir.glob("*.json"):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        job_id = draft.get("job_id")
        if isinstance(job_id, int):
            drafts_by_job_id[job_id] = draft

    return drafts_by_job_id


def _bucket_status(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in ERROR_STATUSES or "error" in normalized or "fail" in normalized:
        return "error"
    if normalized in COMPLETED_STATUSES:
        return "completed"
    if normalized in PENDING_STATUSES:
        return "pending"
    return "active"


def _group_by(items: list, attr_name: str) -> dict[int, list]:
    grouped: dict[int, list] = defaultdict(list)
    for item in items:
        grouped[int(getattr(item, attr_name))].append(item)
    return grouped


def _has_errors(statuses: list[str]) -> bool:
    return any(_bucket_status(status) == "error" for status in statuses)


def _any_active(statuses: list[str]) -> bool:
    return any(_bucket_status(status) == "active" for status in statuses)


def _all_completed(statuses: list[str]) -> bool:
    return bool(statuses) and all(_bucket_status(status) == "completed" for status in statuses)


def _build_stage(
    key: str,
    label: str,
    statuses: list[str],
    *,
    force_completed: bool = False,
    force_active: bool = False,
) -> dict:
    if force_completed:
        stage_status = "completed"
    elif _has_errors(statuses):
        stage_status = "error"
    elif _all_completed(statuses):
        stage_status = "completed"
    elif force_active or _any_active(statuses):
        stage_status = "active"
    else:
        stage_status = "pending"

    return {
        "key": key,
        "label": label,
        "status": stage_status,
    }


def _build_links(video_type: str, job_id: int) -> dict[str, str]:
    if video_type == "cortos":
        return {
            "proceso1": f"/proceso1-corto?jobId={job_id}",
            "proceso2": f"/proceso2-corto?jobId={job_id}",
            "proceso3": f"/proceso3-corto?jobId={job_id}",
            "proceso4": f"/proceso4-corto?jobId={job_id}",
        }

    return {
        "proceso0": "/proceso0",
        "proceso1": f"/proceso1?jobId={job_id}",
        "proceso2": f"/proceso2?jobId={job_id}",
        "proceso3": f"/proceso3?jobId={job_id}",
        "proceso4": f"/proceso4?jobId={job_id}",
        "proceso5": f"/proceso5?jobId={job_id}",
    }


def _pick_current_stage(stages: list[dict]) -> dict:
    for stage in stages:
        if stage["status"] != "completed":
            return stage
    return stages[-1]


def _overall_status(stages: list[dict]) -> str:
    stage_statuses = [stage["status"] for stage in stages]
    if "error" in stage_statuses:
        return "error"
    if all(status == "completed" for status in stage_statuses):
        return "completed"
    if "active" in stage_statuses:
        return "in_progress"
    return "pending"


def _thumbnail_path_from_draft(draft: dict | None) -> str | None:
    if not draft:
        return None
    if not draft.get("thumbnail_image_ext"):
        return None
    draft_id = draft.get("id")
    if not draft_id:
        return None
    return f"/api/proceso0/drafts/{draft_id}/thumbnail-image"


def _serialize_video_item(
    *,
    job_id: int,
    video_type: str,
    title: str,
    raw_idea: str | None,
    video_id: str,
    thumbnail_path: str | None,
    created_at: str | None,
    updated_at: str | None,
    stages: list[dict],
    links: dict[str, str],
) -> dict:
    current_stage = _pick_current_stage(stages)
    completed_count = sum(1 for stage in stages if stage["status"] == "completed")

    return {
        "id": job_id,
        "type": video_type,
        "title": title,
        "rawIdea": raw_idea,
        "videoId": video_id,
        "thumbnailPath": thumbnail_path,
        "currentStage": current_stage["label"],
        "currentStageKey": current_stage["key"],
        "recommendedHref": links[current_stage["key"]],
        "links": links,
        "status": _overall_status(stages),
        "progressLabel": f"{completed_count}/{len(stages)} procesos",
        "progressPercent": int(round((completed_count / len(stages)) * 100)) if stages else 0,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "stages": stages,
    }


def _list_long_videos(limit: int) -> list[dict]:
    jobs = (
        Proceso1Job.query
        .order_by(Proceso1Job.updated_at.desc(), Proceso1Job.id.desc())
        .limit(limit)
        .all()
    )
    if not jobs:
        return []

    job_ids = [job.id for job in jobs]
    drafts_by_job_id = _load_proceso0_drafts()

    proceso1_states = _group_by(
        Proceso1SubprocessState.query.filter(Proceso1SubprocessState.job_id.in_(job_ids)).all(),
        "job_id",
    )
    proceso2_jobs = {item.proceso1_job_id: item for item in Proceso2Job.query.filter(Proceso2Job.proceso1_job_id.in_(job_ids)).all()}
    proceso2_states = _group_by(
        Proceso2SubprocessState.query.filter(Proceso2SubprocessState.proceso1_job_id.in_(job_ids)).all(),
        "proceso1_job_id",
    )
    proceso3_jobs = {item.proceso1_job_id: item for item in Proceso3Job.query.filter(Proceso3Job.proceso1_job_id.in_(job_ids)).all()}
    proceso3_states = _group_by(
        Proceso3SubprocessState.query.filter(Proceso3SubprocessState.proceso1_job_id.in_(job_ids)).all(),
        "proceso1_job_id",
    )
    proceso4_jobs = {item.proceso1_job_id: item for item in Proceso4Job.query.filter(Proceso4Job.proceso1_job_id.in_(job_ids)).all()}
    proceso4_states = _group_by(
        Proceso4SubprocessState.query.filter(Proceso4SubprocessState.proceso1_job_id.in_(job_ids)).all(),
        "proceso1_job_id",
    )
    proceso4_media = _group_by(
        Proceso4SceneMedia.query.filter(Proceso4SceneMedia.proceso1_job_id.in_(job_ids)).all(),
        "proceso1_job_id",
    )
    proceso5_jobs = {item.proceso1_job_id: item for item in Proceso5Job.query.filter(Proceso5Job.proceso1_job_id.in_(job_ids)).all()}
    proceso5_states = _group_by(
        Proceso5SubprocessState.query.filter(Proceso5SubprocessState.proceso1_job_id.in_(job_ids)).all(),
        "proceso1_job_id",
    )

    items: list[dict] = []

    for job in jobs:
        draft = drafts_by_job_id.get(job.id)
        p1_stage_statuses = [job.status] + [source.status for source in job.sources] + [state.status for state in proceso1_states.get(job.id, [])]
        p2_stage_statuses = [proceso2_jobs[job.id].status] if job.id in proceso2_jobs else []
        p2_stage_statuses.extend(state.status for state in proceso2_states.get(job.id, []))
        p3_stage_statuses = [proceso3_jobs[job.id].status] if job.id in proceso3_jobs else []
        p3_stage_statuses.extend(state.status for state in proceso3_states.get(job.id, []))
        p4_stage_statuses = [proceso4_jobs[job.id].status] if job.id in proceso4_jobs else []
        p4_stage_statuses.extend(state.status for state in proceso4_states.get(job.id, []))
        p5_stage_statuses = [proceso5_jobs[job.id].status] if job.id in proceso5_jobs else []
        p5_stage_statuses.extend(state.status for state in proceso5_states.get(job.id, []))

        p1_final_completed = any(
            state.subprocess_key == "subproceso6_final" and _bucket_status(state.status) == "completed"
            for state in proceso1_states.get(job.id, [])
        )
        p2_final_completed = any(
            state.subprocess_key == "scenes" and _bucket_status(state.status) == "completed"
            for state in proceso2_states.get(job.id, [])
        )
        p3_final_completed = any(
            state.subprocess_key == "timeline" and _bucket_status(state.status) == "completed"
            for state in proceso3_states.get(job.id, [])
        )
        p4_final_completed = any(
            state.subprocess_key == "render" and _bucket_status(state.status) == "completed"
            for state in proceso4_states.get(job.id, [])
        )
        p5_final_completed = any(
            state.subprocess_key == "metadata_generation" and _bucket_status(state.status) == "completed"
            for state in proceso5_states.get(job.id, [])
        )

        stages = [
            _build_stage("proceso0", "Proceso 0", [draft.get("status", "")] if draft else [], force_completed=True),
            _build_stage(
                "proceso1",
                "Proceso 1",
                p1_stage_statuses,
                force_completed=p1_final_completed,
                force_active=bool(job.sources or proceso1_states.get(job.id) or job.status != "draft"),
            ),
            _build_stage(
                "proceso2",
                "Proceso 2",
                p2_stage_statuses,
                force_completed=p2_final_completed,
                force_active=bool(job.id in proceso2_jobs or proceso2_states.get(job.id)),
            ),
            _build_stage(
                "proceso3",
                "Proceso 3",
                p3_stage_statuses,
                force_completed=p3_final_completed,
                force_active=bool(job.id in proceso3_jobs or proceso3_states.get(job.id)),
            ),
            _build_stage(
                "proceso4",
                "Proceso 4",
                p4_stage_statuses,
                force_completed=p4_final_completed,
                force_active=bool(job.id in proceso4_jobs or proceso4_states.get(job.id) or proceso4_media.get(job.id)),
            ),
            _build_stage(
                "proceso5",
                "Proceso 5",
                p5_stage_statuses,
                force_completed=p5_final_completed,
                force_active=bool(job.id in proceso5_jobs or proceso5_states.get(job.id)),
            ),
        ]

        title = (job.selected_title or (draft or {}).get("selected_title") or job.video_id or "Sin titulo").strip()
        raw_idea = job.raw_idea or (draft or {}).get("raw_idea")
        links = _build_links("largos", job.id)

        items.append(
            _serialize_video_item(
                job_id=job.id,
                video_type="largos",
                title=title,
                raw_idea=raw_idea,
                video_id=job.video_id,
                thumbnail_path=_thumbnail_path_from_draft(draft),
                created_at=job.created_at.isoformat() if job.created_at else None,
                updated_at=job.updated_at.isoformat() if job.updated_at else None,
                stages=stages,
                links=links,
            )
        )

    return items


def _list_short_videos(limit: int) -> list[dict]:
    jobs = (
        Proceso1CortoJob.query
        .order_by(Proceso1CortoJob.updated_at.desc(), Proceso1CortoJob.id.desc())
        .limit(limit)
        .all()
    )
    if not jobs:
        return []

    job_ids = [job.id for job in jobs]

    proceso1_states = _group_by(
        Proceso1CortoSubprocessState.query.filter(Proceso1CortoSubprocessState.job_id.in_(job_ids)).all(),
        "job_id",
    )
    proceso2_jobs = {item.proceso1_corto_job_id: item for item in Proceso2CortoJob.query.filter(Proceso2CortoJob.proceso1_corto_job_id.in_(job_ids)).all()}
    proceso2_states = _group_by(
        Proceso2CortoSubprocessState.query.filter(Proceso2CortoSubprocessState.proceso1_corto_job_id.in_(job_ids)).all(),
        "proceso1_corto_job_id",
    )
    proceso3_jobs = {item.proceso1_corto_job_id: item for item in Proceso3CortoJob.query.filter(Proceso3CortoJob.proceso1_corto_job_id.in_(job_ids)).all()}
    proceso3_states = _group_by(
        Proceso3CortoSubprocessState.query.filter(Proceso3CortoSubprocessState.proceso1_corto_job_id.in_(job_ids)).all(),
        "proceso1_corto_job_id",
    )
    proceso4_jobs = {item.proceso1_corto_job_id: item for item in Proceso4CortoJob.query.filter(Proceso4CortoJob.proceso1_corto_job_id.in_(job_ids)).all()}
    proceso4_states = _group_by(
        Proceso4CortoSubprocessState.query.filter(Proceso4CortoSubprocessState.proceso1_corto_job_id.in_(job_ids)).all(),
        "proceso1_corto_job_id",
    )
    proceso4_media = _group_by(
        Proceso4CortoSceneMedia.query.filter(Proceso4CortoSceneMedia.proceso1_corto_job_id.in_(job_ids)).all(),
        "proceso1_corto_job_id",
    )

    items: list[dict] = []

    for job in jobs:
        p1_stage_statuses = [job.status] + [state.status for state in proceso1_states.get(job.id, [])]
        p2_stage_statuses = [proceso2_jobs[job.id].status] if job.id in proceso2_jobs else []
        p2_stage_statuses.extend(state.status for state in proceso2_states.get(job.id, []))
        p3_stage_statuses = [proceso3_jobs[job.id].status] if job.id in proceso3_jobs else []
        p3_stage_statuses.extend(state.status for state in proceso3_states.get(job.id, []))
        p4_stage_statuses = [proceso4_jobs[job.id].status] if job.id in proceso4_jobs else []
        p4_stage_statuses.extend(state.status for state in proceso4_states.get(job.id, []))

        p1_final_completed = any(
            state.subprocess_key == "final_script" and _bucket_status(state.status) == "completed"
            for state in proceso1_states.get(job.id, [])
        )
        p2_final_completed = any(
            state.subprocess_key == "scenes" and _bucket_status(state.status) == "completed"
            for state in proceso2_states.get(job.id, [])
        )
        p3_timeline_completed = any(
            state.subprocess_key == "timeline" and _bucket_status(state.status) == "completed"
            for state in proceso3_states.get(job.id, [])
        )
        p3_subtitles_completed = any(
            state.subprocess_key == "subtitles" and _bucket_status(state.status) == "completed"
            for state in proceso3_states.get(job.id, [])
        )
        p4_final_completed = any(
            state.subprocess_key == "render" and _bucket_status(state.status) == "completed"
            for state in proceso4_states.get(job.id, [])
        )

        stages = [
            _build_stage(
                "proceso1",
                "Proceso 1",
                p1_stage_statuses,
                force_completed=p1_final_completed,
                force_active=bool(proceso1_states.get(job.id) or job.status != "created"),
            ),
            _build_stage(
                "proceso2",
                "Proceso 2",
                p2_stage_statuses,
                force_completed=p2_final_completed,
                force_active=bool(job.id in proceso2_jobs or proceso2_states.get(job.id)),
            ),
            _build_stage(
                "proceso3",
                "Proceso 3",
                p3_stage_statuses,
                force_completed=p3_timeline_completed and p3_subtitles_completed,
                force_active=bool(job.id in proceso3_jobs or proceso3_states.get(job.id)),
            ),
            _build_stage(
                "proceso4",
                "Proceso 4",
                p4_stage_statuses,
                force_completed=p4_final_completed,
                force_active=bool(job.id in proceso4_jobs or proceso4_states.get(job.id) or proceso4_media.get(job.id)),
            ),
        ]

        links = _build_links("cortos", job.id)
        items.append(
            _serialize_video_item(
                job_id=job.id,
                video_type="cortos",
                title=(job.video_id or "Video corto").strip(),
                raw_idea=job.video_id,
                video_id=job.video_id,
                thumbnail_path=None,
                created_at=job.created_at.isoformat() if job.created_at else None,
                updated_at=job.updated_at.isoformat() if job.updated_at else None,
                stages=stages,
                links=links,
            )
        )

    return items


@videos_bp.route("", methods=["GET"])
def list_videos():
    video_type = (request.args.get("tipo") or "largos").strip().lower()
    limit = max(1, min(request.args.get("limit", default=100, type=int), 200))

    if video_type not in {"largos", "cortos"}:
        return jsonify({"error": "tipo must be 'largos' or 'cortos'"}), 400

    items = _list_long_videos(limit) if video_type == "largos" else _list_short_videos(limit)
    return jsonify({"items": items, "type": video_type})
