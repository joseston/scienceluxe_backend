"""
Story Architecture -- Encapsulates the structure-generation stage of Proceso 1.

This module owns the decision tree for:
- prompt mode normalization
- solid/freedom structure generation
- hybrid phase A and phase B orchestration
"""
from __future__ import annotations

import json
import re

from .estructura_generator import run_proceso2, step2_generar_prompts
from ..prompts.hybrid_chatgpt import generate_hybrid_chatgpt_prompt


VALID_PROMPT_MODES = ('solid', 'freedom', 'hybrid')
VALID_SP1_PROMPT_MODES = ('solid', 'freedom')


def resolve_prompt_mode(
    requested_mode: object,
    *,
    fallback_mode: str = 'solid',
    allow_hybrid: bool = False,
) -> str:
    allowed_modes = VALID_PROMPT_MODES if allow_hybrid else VALID_SP1_PROMPT_MODES
    prompt_mode = str(requested_mode or fallback_mode).strip()
    if prompt_mode not in allowed_modes:
        return fallback_mode if fallback_mode in allowed_modes else 'solid'
    return prompt_mode


def _extract_json_blob(raw_text: str) -> str:
    match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text, re.IGNORECASE)
    if not match:
        match = re.search(r"```\s*([\s\S]*?)\s*```", raw_text)
    if match:
        return match.group(1).strip()

    first_brace = raw_text.find('{')
    last_brace = raw_text.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        return raw_text[first_brace:last_brace + 1].strip()
    return raw_text.strip()


def _normalize_keywords(value: object) -> list[str]:
    if isinstance(value, list):
        keywords = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        keywords = [part.strip() for part in value.split(',') if part.strip()]
    else:
        keywords = []

    return keywords[:7]


def _normalize_subtemas(value: object, *, min_items: int, max_items: int | None = None, exact_items: int | None = None) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError('subtemas must be an array')

    subtemas: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        titulo = str(item.get('titulo') or item.get('title') or '').strip()
        contexto = str(item.get('contexto') or item.get('context') or '').strip()
        if titulo and contexto:
            subtemas.append({
                'titulo': titulo,
                'contexto': contexto,
            })

    if exact_items is not None and len(subtemas) != exact_items:
        raise ValueError(f'subtemas must contain exactly {exact_items} items')
    if len(subtemas) < min_items:
        raise ValueError(f'subtemas must contain at least {min_items} items')
    if max_items is not None and len(subtemas) > max_items:
        subtemas = subtemas[:max_items]
    return subtemas


def _normalize_structure(
    payload: object,
    *,
    selected_title: str = '',
    min_subtopics: int = 3,
    max_subtopics: int | None = 8,
    exact_subtopics: int | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('structure payload must be an object')

    tema_principal = str(
        payload.get('tema_principal')
        or payload.get('main_topic')
        or payload.get('topic')
        or selected_title
        or ''
    ).strip()
    if not tema_principal:
        raise ValueError('tema_principal is required')

    keywords = _normalize_keywords(payload.get('keywords'))
    subtemas = _normalize_subtemas(
        payload.get('subtemas'),
        min_items=min_subtopics,
        max_items=max_subtopics,
        exact_items=exact_subtopics,
    )

    return {
        'tema_principal': selected_title or tema_principal,
        'selected_title': selected_title or str(payload.get('selected_title') or '').strip(),
        'keywords': keywords,
        'subtemas': subtemas,
    }


def parse_manual_hybrid_output(raw_text: str, *, selected_title: str = '') -> dict:
    json_blob = _extract_json_blob(raw_text)
    parsed = json.loads(json_blob)
    if not isinstance(parsed, dict):
        raise ValueError('The pasted output must be a JSON object')

    estructura_libre = _normalize_structure(
        parsed.get('estructura_libre'),
        selected_title=selected_title,
        min_subtopics=4,
        max_subtopics=8,
    )
    estructura_final = _normalize_structure(
        parsed.get('estructura_final'),
        selected_title=selected_title,
        min_subtopics=4,
        max_subtopics=4,
        exact_subtopics=4,
    )

    return {
        'estructuraLibre': estructura_libre,
        'estructura': estructura_final,
    }


def run_story_structure_stage(
    *,
    analysis_text: str,
    raw_sources_text: str,
    prompt_mode: str,
    selected_title: str = '',
    project_external_id: str | None = None,
) -> dict:
    if prompt_mode == 'hybrid':
        hybrid_prompt = generate_hybrid_chatgpt_prompt(
            analysis_text,
            selected_title=selected_title,
        )
        return {
            'status': 'awaiting_manual_hybrid_output',
            'output': {
                'hybridPrompt': hybrid_prompt,
                'expectedOutputFormat': 'json_only',
            },
        }

    result = run_proceso2(
        analisis_texto=analysis_text,
        datos_crudos_texto=raw_sources_text,
        project_external_id=project_external_id,
        prompt_mode=prompt_mode,
        selected_title=selected_title,
    )

    estructura_result = result.get('estructura', {})
    if selected_title and isinstance(estructura_result, dict):
        estructura_result['tema_principal'] = selected_title

    return {
        'status': 'completed',
        'output': {
            'estructura': estructura_result,
            'deepResearchPrompt': (result.get('deep_research') or {}).get('prompt_completo', ''),
            'infoInternaPrompt': (result.get('info_interna') or {}).get('prompt_completo', ''),
        },
    }


def complete_hybrid_story_structure(
    *,
    hybrid_output_text: str,
    raw_sources_text: str,
    selected_title: str = '',
    existing_output: dict | None = None,
) -> dict:
    parsed_output = parse_manual_hybrid_output(
        hybrid_output_text,
        selected_title=selected_title,
    )
    estructura_final = parsed_output['estructura']
    prompts = step2_generar_prompts(
        estructura_final,
        raw_sources_text,
        selected_title=selected_title,
    )

    return {
        'status': 'completed',
        'output': {
            **(existing_output or {}),
            'estructuraLibre': parsed_output['estructuraLibre'],
            'estructura': estructura_final,
            'deepResearchPrompt': (prompts.get('deep_research') or {}).get('prompt_completo', ''),
            'infoInternaPrompt': (prompts.get('info_interna') or {}).get('prompt_completo', ''),
        },
    }
