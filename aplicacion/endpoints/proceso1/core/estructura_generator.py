"""
Estructura Generator — GET INFORMATION: Lógica core.
Proceso 1, Sub-proceso 2. Gemini AI → estructura + prompts finales.
"""
import json
import re
import time
import traceback
from config import GEMINI_API_KEY, GEMINI_MODEL
from ..prompts.generar_estructura import generate_estructura_prompt
from ..prompts.deep_research import generate_deep_research_prompt
from ..prompts.info_interna import generate_info_interna_prompt
from aplicacion.services.gemini_compat import generate_text, get_sdk_label

try:
    from core.database import (
        db_session,
        ensure_project,
        insert_llm_call,
        insert_prompt_artifact,
    )
except ModuleNotFoundError:
    db_session = None
    ensure_project = None
    insert_llm_call = None
    insert_prompt_artifact = None


def _call_gemini(prompt: str) -> str:
    """Llama a Gemini API y retorna el texto de respuesta."""
    print("\n" + "=" * 60)
    print("🤖 GEMINI API CALL")
    print("=" * 60)
    print(f"📌 Modelo: {GEMINI_MODEL}")
    print(f"📦 SDK: {get_sdk_label()}")
    print(f"🔑 API Key: {GEMINI_API_KEY[:10]}...{GEMINI_API_KEY[-4:]}")
    print(f"📝 Prompt length: {len(prompt)} caracteres")
    print(f"📝 Prompt preview: {prompt[:200]}...")
    print("-" * 60)
    print("⏳ Enviando request a Gemini...")

    try:
        response_text = generate_text(
            api_key=GEMINI_API_KEY,
            model=GEMINI_MODEL,
            prompt=prompt,
        )
        print(f"✅ Respuesta recibida!")
        print(f"📏 Response length: {len(response_text)} caracteres")
        print(f"📄 Response preview: {response_text[:300]}...")
        print("=" * 60 + "\n")
        
        return response_text
        
    except Exception as e:
        print(f"❌ ERROR en Gemini API:")
        print(f"   {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        print("=" * 60 + "\n")
        raise


def _persist_proceso2_data(
    project_external_id: str | None,
    prompt_estructura: str,
    raw_response: str,
    deep_prompt: str,
    info_prompt: str,
    latency_ms: int,
):
    if (
        not project_external_id
        or db_session is None
        or ensure_project is None
        or insert_llm_call is None
        or insert_prompt_artifact is None
    ):
        return

    try:
        with db_session() as session:
            project = ensure_project(session, project_external_id=project_external_id)
            insert_llm_call(
                session=session,
                project_id=project.id,
                stage="p2",
                provider="gemini",
                model=GEMINI_MODEL,
                prompt_text=prompt_estructura,
                response_text=raw_response,
                latency_ms=latency_ms,
            )
            insert_prompt_artifact(
                session=session,
                project_id=project.id,
                stage="p2",
                prompt_type="deep_research",
                prompt_full=deep_prompt,
            )
            insert_prompt_artifact(
                session=session,
                project_id=project.id,
                stage="p2",
                prompt_type="info_interna",
                prompt_full=info_prompt,
            )
    except Exception:
        pass


def _parse_json_response(raw_text: str) -> dict:
    """Parsea la respuesta de Gemini extrayendo el JSON."""
    print("🔧 Parseando JSON de la respuesta...")

    match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text)
    if not match:
        match = re.search(r"```\s*([\s\S]*?)\s*```", raw_text)

    json_str = match.group(1) if match else raw_text

    try:
        result = json.loads(json_str)
        print(f"✅ JSON parseado: {list(result.keys())}")
        return result
    except json.JSONDecodeError as e:
        print(f"⚠️ Primer intento de parseo falló: {e}")
        cleaned = json_str.strip()
        result = json.loads(cleaned)
        print(f"✅ JSON parseado (2do intento): {list(result.keys())}")
        return result


def step1_generar_estructura(analisis_texto: str, prompt_mode: str = "solid", selected_title: str = "") -> tuple[dict, str, str, int]:
    """
    Step 1: Envía el análisis estratégico a Gemini para obtener estructura.
    """
    print("\n🚀 STEP 1: Generando estructura con AI...")
    print(f"   Input text length: {len(analisis_texto)} chars")
    print(f"   Prompt mode: {prompt_mode}")
    print(f"   Selected title: {selected_title or '(none)'}")
    
    prompt = generate_estructura_prompt(analisis_texto, prompt_mode=prompt_mode, selected_title=selected_title)
    started_at = time.perf_counter()
    raw_response = _call_gemini(prompt)
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    estructura = _parse_json_response(raw_response)
    
    print(f"   Tema principal: {estructura.get('tema_principal', '?')}")
    print(f"   Subtemas: {len(estructura.get('subtemas', []))}")
    print(f"   Keywords: {estructura.get('keywords', [])}")
    
    return estructura, prompt, raw_response, latency_ms


def step2_generar_prompts(estructura: dict, datos_crudos_texto: str, selected_title: str = "") -> dict:
    """
    Step 2: Genera los 2 prompts finales.
    """
    print("\n🚀 STEP 2: Generando prompts finales...")
    print(f"   Datos crudos length: {len(datos_crudos_texto)} chars")

    deep_research = generate_deep_research_prompt(estructura, selected_title=selected_title)
    info_interna = generate_info_interna_prompt(estructura, datos_crudos_texto, selected_title=selected_title)

    print(f"   ✅ Deep Research prompt: {len(deep_research['prompt_completo'])} chars")
    print(f"   ✅ Info Interna prompt: {len(info_interna['prompt_completo'])} chars")

    return {
        "deep_research": deep_research,
        "info_interna": info_interna,
    }


def run_proceso2(
    analisis_texto: str,
    datos_crudos_texto: str,
    on_status=None,
    project_external_id: str | None = None,
    prompt_mode: str = "solid",
    selected_title: str = "",
) -> dict:
    """Ejecuta el Proceso 2 completo."""
    print("\n" + "🔶" * 30)
    print("  PROCESO 2 — GET INFORMATION — INICIANDO")
    print(f"  Prompt Mode: {prompt_mode}")
    print(f"  Selected Title: {selected_title or '(none)'}")
    print("🔶" * 30)

    if on_status:
        on_status("🔄 Enviando análisis a Gemini AI...")

    estructura, prompt_estructura, raw_response, latency_ms = step1_generar_estructura(
        analisis_texto, prompt_mode=prompt_mode, selected_title=selected_title
    )

    if on_status:
        on_status("✅ Estructura generada. Creando prompts finales...")

    prompts = step2_generar_prompts(estructura, datos_crudos_texto, selected_title=selected_title)

    _persist_proceso2_data(
        project_external_id=project_external_id,
        prompt_estructura=prompt_estructura,
        raw_response=raw_response,
        deep_prompt=prompts["deep_research"]["prompt_completo"],
        info_prompt=prompts["info_interna"]["prompt_completo"],
        latency_ms=latency_ms,
    )

    if on_status:
        on_status("✅ Proceso 2 completado")

    print("\n" + "✅" * 30)
    print("  PROCESO 2 — COMPLETADO EXITOSAMENTE")
    print("✅" * 30 + "\n")

    return {
        "estructura": estructura,
        "deep_research": prompts["deep_research"],
        "info_interna": prompts["info_interna"],
    }
