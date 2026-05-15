"""
Estructura Generator — Lógica core para Videos Cortos.
Proceso 1 Corto, Sub-proceso 2. Gemini AI → estructura corta + prompts finales.
"""
import json
import re
import time
import traceback
from config import GEMINI_API_KEY, GEMINI_MODEL
from ..prompts.generar_estructura import generate_estructura_prompt
from ..prompts.deep_research import generate_deep_research_prompt, generate_info_interna_prompt
from aplicacion.services.gemini_compat import generate_text, get_sdk_label


def _call_gemini(prompt: str) -> str:
    """Llama a Gemini API y retorna el texto de respuesta."""
    print("\n" + "=" * 60)
    print("🤖 GEMINI API CALL (Video Corto)")
    print("=" * 60)
    print(f"📌 Modelo: {GEMINI_MODEL}")
    print(f"📦 SDK: {get_sdk_label()}")
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


def step1_generar_estructura(analisis_texto: str) -> tuple[dict, str, str, int]:
    """
    Step 1: Envía el análisis estratégico a Gemini para obtener estructura corta.
    """
    print("\n🚀 STEP 1 (Corto): Generando estructura corta con AI...")
    print(f"   Input text length: {len(analisis_texto)} chars")

    prompt = generate_estructura_prompt(analisis_texto)
    started_at = time.perf_counter()
    raw_response = _call_gemini(prompt)
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    estructura = _parse_json_response(raw_response)

    print(f"   Tema principal: {estructura.get('tema_principal', '?')}")
    print(f"   Ángulo/Hook: {estructura.get('angulo_hook', '?')[:80]}...")
    print(f"   Keywords: {estructura.get('keywords', [])}")

    return estructura, prompt, raw_response, latency_ms


def step2_generar_prompts(estructura: dict, datos_crudos_texto: str) -> dict:
    """
    Step 2: Genera los 2 prompts finales (deep research + info interna).
    """
    print("\n🚀 STEP 2 (Corto): Generando prompts finales...")
    print(f"   Datos crudos length: {len(datos_crudos_texto)} chars")

    deep_research = generate_deep_research_prompt(estructura)
    info_interna = generate_info_interna_prompt(estructura, datos_crudos_texto)

    print(f"   ✅ Deep Research prompt: {len(deep_research['prompt_completo'])} chars")
    print(f"   ✅ Info Interna prompt: {len(info_interna['prompt_completo'])} chars")

    return {
        "deep_research": deep_research,
        "info_interna": info_interna,
    }


def run_proceso2_corto(
    analisis_texto: str,
    datos_crudos_texto: str,
    on_status=None,
) -> dict:
    """Ejecuta el Proceso 2 Corto completo."""
    print("\n" + "🔷" * 30)
    print("  PROCESO 2 CORTO — GET INFORMATION — INICIANDO")
    print("🔷" * 30)

    if on_status:
        on_status("🔄 Enviando análisis a Gemini AI (formato corto)...")

    estructura, prompt_estructura, raw_response, latency_ms = step1_generar_estructura(analisis_texto)

    if on_status:
        on_status("✅ Estructura corta generada. Creando prompts finales...")

    prompts = step2_generar_prompts(estructura, datos_crudos_texto)

    if on_status:
        on_status("✅ Proceso 2 Corto completado")

    print("\n" + "✅" * 30)
    print("  PROCESO 2 CORTO — COMPLETADO EXITOSAMENTE")
    print("✅" * 30 + "\n")

    return {
        "estructura": estructura,
        "deep_research": prompts["deep_research"],
        "info_interna": prompts["info_interna"],
    }
