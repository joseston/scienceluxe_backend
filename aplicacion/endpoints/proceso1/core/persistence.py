"""
Persistence — Capa de alto nivel para guardar/cargar artefactos del Proceso 1.

Cada sub-proceso guarda sus datos en la tabla `p1_artifacts` usando
claves estandarizadas.  Las funciones centralizan la lógica para que
las vistas solo llamen  `save_*()` / `load_*()`.
"""
from __future__ import annotations

from core.database import (
    db_session,
    ensure_project,
    save_artifact,
    load_artifact,
    load_all_artifacts,
    update_project_metadata,
    list_projects_with_status,
    replace_project_sources,
    P1Artifact,
    Project,
    Source,
)
from sqlalchemy import select


def _sanitize_text(value: str) -> str:
    """Normaliza texto para entornos con codificación legacy (cp1252/charmap)."""
    if not isinstance(value, str):
        return value
    return value.encode("cp1252", errors="replace").decode("cp1252")


def _sanitize_obj(value):
    """Sanitiza recursivamente dict/list/str para persistencia robusta."""
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_obj(item) for item in value]
    if isinstance(value, dict):
        return {k: _sanitize_obj(v) for k, v in value.items()}
    return value


def _save_artifact_safe(session, project_id: int, key: str, text: str | None = None, json_data=None):
    """Guarda artefacto con fallback de sanitización para UnicodeEncodeError."""
    safe_text = _sanitize_text(text) if text is not None else None
    safe_json = _sanitize_obj(json_data) if json_data is not None else None
    save_artifact(session, project_id, key, text=safe_text, json_data=safe_json)

# ─── Claves de artefactos (constantes) ────────────────────────────
AK_INPUT_URLS           = "input_urls"
AK_P1_SOURCES           = "p1_sources"
AK_P1_AGGREGATED        = "p1_aggregated"
AK_P1_PROMPTS           = "p1_prompts"
AK_P2_ANALYSIS_INPUT    = "p2_analysis_input"
AK_P2_ESTRUCTURA        = "p2_estructura"
AK_P2_DR_PROMPT         = "p2_deep_research_prompt"
AK_P2_II_PROMPT         = "p2_info_interna_prompt"
AK_P3_KEYWORD           = "p3_keyword"
AK_P3_DR_OUTPUT         = "p3_deep_research_output"
AK_P3_II_OUTPUT         = "p3_info_interna_output"
AK_P3_INTRO_PROMPT      = "p3_intro_prompt"
AK_P3_ENSAM_INPUTS      = "p3_ensamblaje_inputs"
AK_P3_ENSAM_PROMPT      = "p3_ensamblaje_prompt"
AK_P4_INTRO_FINAL       = "p4_intro_final"
AK_P4_SUBTEMA_PROMPTS   = "p4_subtema_prompts"
AK_P4_SUBTEMA_SCRIPTS   = "p4_subtema_scripts"
AK_P5_CIERRE_PROMPT     = "p5_cierre_prompt"
AK_P5_CIERRE_SCRIPT     = "p5_cierre_script"
AK_SCRIPT_FINAL         = "script_final"

# Mapa sub-proceso → etiqueta para metadata
SUBPROCESS_LABELS = {
    0: "Subproceso 1 — Input URLs",
    1: "Subproceso 1 — Extracción",
    2: "Subproceso 1 — Prompt P1",
    3: "Subproceso 2 — Input P2",
    4: "Subproceso 2 — Prompts P2",
    5: "Subproceso 3 — Input P3",
    6: "Subproceso 3 — Prompt Intro",
    7: "Subproceso 3 — Ensamblaje Input",
    8: "Subproceso 3 — Prompt Ensamblaje",
    9: "Subproceso 4 — Input P4",
    10: "Subproceso 4 — Prompt Cuerpo",
    11: "Subproceso 5 — Input Cierre",
    12: "Subproceso 5 — Prompt Cierre",
    13: "Subproceso 5 — Script Final",
}


# ═══════════════════════════════════════════
# Helpers internos
# ═══════════════════════════════════════════

def _get_project_db_id(session, external_id: str) -> int | None:
    """Retorna el id interno de un proyecto, o None."""
    project = session.scalar(
        select(Project).where(Project.external_id == external_id)
    )
    return project.id if project else None


# ═══════════════════════════════════════════
# API pública — Guardar
# ═══════════════════════════════════════════

def create_or_get_project(external_id: str) -> int:
    """Crea un proyecto (o lo obtiene si ya existe). Retorna db_id."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        update_project_metadata(session, project.id, {
            "pipeline_status": "in_progress",
        })
        return project.id


def save_input_urls(external_id: str, video_id: str, urls: list[str]):
    """Guarda las URLs de entrada en p1_artifacts."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_INPUT_URLS, json_data={
            "video_id": video_id,
            "urls": urls,
        })
        update_project_metadata(session, project.id, {
            "current_subprocess": 0,
            "last_subprocess_label": SUBPROCESS_LABELS[0],
        })


def save_extraction_results(external_id: str, sources: list[dict], aggregated: dict, prompts: dict):
    """Guarda resultados de extracción + json agregado + prompts P1."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        # Fuentes en tabla sources (ya existente)
        replace_project_sources(session, project_id=pid, sources=sources)
        # Artefactos
        _save_artifact_safe(session, pid, AK_P1_SOURCES, json_data=sources)
        _save_artifact_safe(session, pid, AK_P1_AGGREGATED, json_data=aggregated)
        _save_artifact_safe(session, pid, AK_P1_PROMPTS, json_data=prompts)
        update_project_metadata(session, pid, {
            "current_subprocess": 2,
            "last_subprocess_label": SUBPROCESS_LABELS[2],
        })


def save_p2_input(external_id: str, analysis_text: str):
    """Guarda el texto de análisis estratégico pegado por el usuario."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_P2_ANALYSIS_INPUT, text=analysis_text)


def save_p2_results(external_id: str, estructura: dict,
                    deep_research_prompt: str, info_interna_prompt: str):
    """Guarda resultados del Proceso 2 (estructura + prompts)."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        _save_artifact_safe(session, pid, AK_P2_ESTRUCTURA, json_data=estructura)
        _save_artifact_safe(session, pid, AK_P2_DR_PROMPT, text=deep_research_prompt)
        _save_artifact_safe(session, pid, AK_P2_II_PROMPT, text=info_interna_prompt)
        update_project_metadata(session, pid, {
            "current_subprocess": 4,
            "last_subprocess_label": SUBPROCESS_LABELS[4],
        })


def save_p3_inputs(external_id: str, keyword: str,
                   deep_output: str, interna_output: str):
    """Guarda los textos pegados por el usuario en P3."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        _save_artifact_safe(session, pid, AK_P3_KEYWORD, text=keyword)
        _save_artifact_safe(session, pid, AK_P3_DR_OUTPUT, text=deep_output)
        _save_artifact_safe(session, pid, AK_P3_II_OUTPUT, text=interna_output)


def save_p3_intro_prompt(external_id: str, intro_data: dict):
    """Guarda el prompt de introducción generado."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        _save_artifact_safe(session, pid, AK_P3_INTRO_PROMPT, json_data=intro_data)
        update_project_metadata(session, pid, {
            "current_subprocess": 6,
            "last_subprocess_label": SUBPROCESS_LABELS[6],
        })


def save_p3_ensamblaje(external_id: str, inputs: dict, prompt_data: dict):
    """Guarda inputs y prompt de ensamblaje."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        _save_artifact_safe(session, pid, AK_P3_ENSAM_INPUTS, json_data=inputs)
        _save_artifact_safe(session, pid, AK_P3_ENSAM_PROMPT, json_data=prompt_data)
        update_project_metadata(session, pid, {
            "current_subprocess": 8,
            "last_subprocess_label": SUBPROCESS_LABELS[8],
        })


def save_p4_intro(external_id: str, intro_text: str):
    """Guarda la introducción final."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_P4_INTRO_FINAL, text=intro_text)


def save_p4_subtema(external_id: str, index: int, prompt_data: dict | None, script: str | None):
    """Guarda prompt y/o script de un subtema (merge incremental)."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        pid = project.id
        if prompt_data is not None:
            # Cargar lista actual y actualizar posición
            art = load_artifact(session, pid, AK_P4_SUBTEMA_PROMPTS)
            current = (art.content_json if art and art.content_json else
                       [{}, {}, {}, {}])
            current[index] = prompt_data
            _save_artifact_safe(session, pid, AK_P4_SUBTEMA_PROMPTS, json_data=current)

        if script is not None:
            art = load_artifact(session, pid, AK_P4_SUBTEMA_SCRIPTS)
            current = (art.content_json if art and art.content_json else
                       ["", "", "", ""])
            current[index] = script
            _save_artifact_safe(session, pid, AK_P4_SUBTEMA_SCRIPTS, json_data=current)
            update_project_metadata(session, pid, {
                "current_subprocess": 9,
                "last_subprocess_label": f"Subproceso 4 — Subtema {index + 1}/4",
            })


def save_p5_cierre_prompt(external_id: str, prompt_data: dict):
    """Guarda el prompt de cierre."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_P5_CIERRE_PROMPT, json_data=prompt_data)
        update_project_metadata(session, project.id, {
            "current_subprocess": 12,
            "last_subprocess_label": SUBPROCESS_LABELS[12],
        })


def save_p5_cierre_script(external_id: str, script: str):
    """Guarda el script de cierre."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_P5_CIERRE_SCRIPT, text=script)


def save_script_final(external_id: str, script: str):
    """Guarda el script final completo."""
    with db_session() as session:
        project = ensure_project(session, project_external_id=external_id)
        _save_artifact_safe(session, project.id, AK_SCRIPT_FINAL, text=script)
        update_project_metadata(session, project.id, {
            "current_subprocess": 13,
            "last_subprocess_label": SUBPROCESS_LABELS[13],
            "pipeline_status": "completed",
        })


# ═══════════════════════════════════════════
# API pública — Cargar
# ═══════════════════════════════════════════

def load_project_full(external_id: str) -> dict | None:
    """Carga TODOS los artefactos de un proyecto.

    Retorna un dict con cada artifact_key como clave, o None si el
    proyecto no existe.  Formato:
      { "input_urls": {"text": ..., "json": ...}, ... }
    """
    try:
        with db_session() as session:
            project = session.scalar(
                select(Project).where(Project.external_id == external_id)
            )
            if not project:
                return None

            artifacts = load_all_artifacts(session, project.id)
            meta = project.metadata_json or {}

            return {
                "db_id": project.id,
                "external_id": project.external_id,
                "metadata": meta,
                "artifacts": artifacts,
                "created_at": project.created_at.isoformat() if project.created_at else "",
            }
    except Exception as exc:
        print(f"⚠️ Error cargando proyecto {external_id}: {exc}")
        return None


def list_projects() -> list[dict]:
    """Lista todos los proyectos con su estado de pipeline."""
    try:
        with db_session() as session:
            return list_projects_with_status(session)
    except Exception as exc:
        print(f"⚠️ Error listando proyectos: {exc}")
        return []


def delete_project_full(external_id: str) -> bool:
    """Elimina un proyecto y todos sus artefactos (CASCADE)."""
    try:
        with db_session() as session:
            project = session.scalar(
                select(Project).where(Project.external_id == external_id)
            )
            if project:
                session.delete(project)
                return True
    except Exception as exc:
        print(f"⚠️ Error eliminando proyecto: {exc}")
    return False
