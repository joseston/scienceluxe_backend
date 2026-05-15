"""
Generar Estructura Corta — Prompt para que Gemini extraiga estructura JSON
optimizada para videos cortos (TikTok/YouTube Shorts).

A diferencia de la versión larga (4 subtemas), aquí se busca:
- 1 ángulo/hook
- 1 punto principal
- 1 CTA
"""


def generate_estructura_prompt(analisis_previo: str) -> str:
    """
    Generates the prompt sent to Gemini to extract a SHORT-FORM video structure.
    Returns a compact JSON with hook, main point, and CTA instead of 4 subtopics.
    """
    plantilla = """ROLE: You are a JSON Data Structuring Assistant specialized in short-form video content.
OBJECTIVE: Convert the strategic analysis of a SHORT VIDEO (30s-2min) into a strict and validated JSON object.

INPUT (STRATEGIC ANALYSIS):
[INSERTAR_ANALISIS_AQUI]

PROCESSING INSTRUCTIONS:
1. Read the entire analysis.
2. Extract the main topic as 'tema_principal'.
3. Extract the BEST viral hook as 'angulo_hook' (1-2 compelling sentences that stop the scroll).
4. Extract the SINGLE most important insight/point as 'punto_principal' (2-3 sentences).
5. Write a compelling CTA as 'cta' (call to action — follow, like, comment, or share).
6. Identify 3-5 key words or concepts and put them in 'keywords'.
7. Suggest the best platform target in 'plataforma_target' (either "tiktok" or "shorts").

OUTPUT FORMAT (SINGLE JSON ONLY):
{
  "tema_principal": "The main topic",
  "angulo_hook": "The viral hook — 1-2 sentences that stop the scroll",
  "punto_principal": "The single core insight — 2-3 sentences explaining the main point",
  "cta": "Call to action for the viewer",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "plataforma_target": "tiktok or shorts",
  "tono_sugerido": "conversational | dramatic | educational | humorous"
}

IMPORTANT: Return ONLY the JSON. Do not add any text before or after."""

    return plantilla.replace("[INSERTAR_ANALISIS_AQUI]", analisis_previo)
