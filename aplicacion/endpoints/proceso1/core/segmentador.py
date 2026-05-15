"""
Segmentador — Auto-segmenta info_externa e info_interna por subtema usando Gemini Flash.

Flujo:
1. Recibe los 2 bloques completos (info_externa, info_interna) + estructura (subtemas)
2. Para cada subtema, llama a Gemini Flash para extraer los párrafos relevantes
3. Lanza 2 llamadas en paralelo, espera 60s, siguientes 2, etc. (free tier)
4. Retorna un dict {subtema_1: {infoExterna: "...", infoInterna: "..."}, ...}
"""
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

SEGMENTATION_PROMPT = """You are a text segmentation assistant. Your ONLY job is to extract the paragraphs from a large text that are relevant to a specific subtopic.

SUBTOPIC TITLE: "{titulo}"
SUBTOPIC CONTEXT: "{contexto}"

FULL TEXT TO SEGMENT:
---
{texto_completo}
---

INSTRUCTIONS:
1. Read the full text above carefully.
2. Identify ALL paragraphs, sentences, or sections that contain information relevant to the subtopic "{titulo}" (context: {contexto}).
3. Copy those paragraphs VERBATIM — do not summarize, rewrite, or add anything.
4. If a paragraph is partially relevant, include the ENTIRE paragraph.
5. Maintain the original order of the paragraphs.
6. If NO paragraphs are relevant to this subtopic, return exactly: "(No relevant information found)"

OUTPUT: Return ONLY the extracted paragraphs, nothing else. No headers, no labels, no commentary."""


def _call_gemini_for_segmentation(api_key: str, model_name: str, prompt: str) -> str:
    """Call Gemini API for a single segmentation task."""
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError('pip install google-generativeai') from exc

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(prompt)
    return resp.text or ''


def _segment_one_subtema(
    api_key: str,
    model_name: str,
    subtema: dict,
    info_externa: str,
    info_interna: str,
) -> dict:
    """Segment both info blocks for a single subtema."""
    titulo = subtema.get('titulo', '?')
    contexto = subtema.get('contexto', '')

    result = {'titulo': titulo, 'infoExterna': '', 'infoInterna': ''}

    # Segment info_externa
    if info_externa.strip():
        prompt_ext = SEGMENTATION_PROMPT.format(
            titulo=titulo,
            contexto=contexto,
            texto_completo=info_externa,
        )
        try:
            result['infoExterna'] = _call_gemini_for_segmentation(api_key, model_name, prompt_ext)
        except Exception as e:
            logger.error(f"Error segmenting info_externa for '{titulo}': {e}")
            result['infoExterna'] = f"(Error: {e})"

    # Segment info_interna
    if info_interna.strip():
        prompt_int = SEGMENTATION_PROMPT.format(
            titulo=titulo,
            contexto=contexto,
            texto_completo=info_interna,
        )
        try:
            result['infoInterna'] = _call_gemini_for_segmentation(api_key, model_name, prompt_int)
        except Exception as e:
            logger.error(f"Error segmenting info_interna for '{titulo}': {e}")
            result['infoInterna'] = f"(Error: {e})"

    return result


def segment_info_by_subtemas(
    api_key: str,
    model_name: str,
    subtemas: list[dict],
    info_externa: str,
    info_interna: str,
    parallel: int = 2,
    wait_seconds: int = 60,
    on_progress=None,
) -> dict:
    """
    Segment info_externa and info_interna into per-subtema chunks.

    Each subtema gets TWO Gemini calls (one for info_externa, one for info_interna).
    We launch `parallel` subtemas at a time (each subtema = 2 sequential calls),
    then wait `wait_seconds` before the next batch.

    Returns: {
        "subtema_1": {"titulo": "...", "infoExterna": "...", "infoInterna": "..."},
        "subtema_2": {...},
        ...
    }
    """
    results = {}
    total = len(subtemas)

    # Process in batches of `parallel`
    for batch_start in range(0, total, parallel):
        batch_end = min(batch_start + parallel, total)
        batch = subtemas[batch_start:batch_end]
        batch_indices = list(range(batch_start, batch_end))

        if on_progress:
            on_progress(f"Processing subtemas {batch_start + 1}-{batch_end} of {total}...")

        logger.info(f"Segmentation batch: subtemas {batch_start + 1}-{batch_end}")

        # Launch batch in parallel using threads
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {}
            for i, subtema in zip(batch_indices, batch):
                future = executor.submit(
                    _segment_one_subtema,
                    api_key, model_name, subtema,
                    info_externa, info_interna,
                )
                futures[future] = i

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    results[f"subtema_{idx + 1}"] = result
                    logger.info(f"✅ Subtema {idx + 1} segmented: "
                                f"ext={len(result.get('infoExterna', ''))} chars, "
                                f"int={len(result.get('infoInterna', ''))} chars")
                except Exception as e:
                    logger.error(f"❌ Subtema {idx + 1} failed: {e}")
                    traceback.print_exc()
                    results[f"subtema_{idx + 1}"] = {
                        'titulo': subtemas[idx].get('titulo', '?'),
                        'infoExterna': f'(Error: {e})',
                        'infoInterna': f'(Error: {e})',
                    }

        # Wait between batches (except after the last batch)
        if batch_end < total:
            if on_progress:
                on_progress(f"Rate limit: waiting {wait_seconds}s before next batch...")
            logger.info(f"⏳ Rate limit wait: {wait_seconds}s")
            time.sleep(wait_seconds)

    if on_progress:
        on_progress(f"✅ Segmentation complete: {total} subtemas processed")

    return results
