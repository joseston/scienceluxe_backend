"""
Generar Estructura — Prompt para que Gemini extraiga estructura JSON.
V2: Supports both "solid" (4 subtopics) and "freedom" (N subtopics) modes.

Translated to English for US audience context.
Parte del paquete proceso1.prompts.
"""


def generate_estructura_prompt(analisis_previo: str, prompt_mode: str = "solid", selected_title: str = "") -> str:
    """
    Generates the prompt sent to Gemini to extract
    main_topic, keywords, and subtopics from the strategic analysis.
    
    Args:
        analisis_previo: The strategic analysis text.
        prompt_mode: "solid" expects exactly 4 subtopics, "freedom" extracts all found.
        selected_title: The chosen video title from Proceso 0 (the North Star).
    """
    if prompt_mode == "solid":
        subtema_instruction = (
            "4. Extract the 4 subtopics of the structure. For each:\n"
            "   - 'titulo': The name of the subtopic.\n"
            "   - 'contexto': Write 2 or 3 sentences summarizing what this subtopic is specifically about, "
            "based on the original text. This will serve as context for deep research.\n"
        )
        repeat_note = "... (repeat for all 4 subtopics)"
    else:
        subtema_instruction = (
            "4. Extract ALL subtopics/sections from the Retention Architecture. "
            "The analysis may contain anywhere from 3 to 8 sections — extract every single one. For each:\n"
            "   - 'titulo': The name of the subtopic/section.\n"
            "   - 'contexto': Write 2 or 3 sentences summarizing what this subtopic is specifically about, "
            "based on the original text. This will serve as context for deep research.\n"
        )
        repeat_note = "... (repeat for ALL subtopics found in the analysis — could be 3 to 8)"

    title_block = ""
    if selected_title:
        title_block = (
            f'\nCHOSEN VIDEO TITLE: "{selected_title}"\n'
            "ALIGNMENT RULE: The 'tema_principal' and every subtopic must be clearly aligned "
            "with delivering on this title's promise to the viewer. Include the title angle in "
            "the 'contexto' of each subtopic.\n"
        )

    plantilla = f"""ROLE: You are a JSON Data Structuring Assistant.
OBJECTIVE: Convert the strategic analysis of a video (plain text) into a strict and validated JSON object.
{title_block}
INPUT (STRATEGIC ANALYSIS):
[INSERTAR_ANALISIS_AQUI]

PROCESSING INSTRUCTIONS:
1. Read the entire analysis.
2. Extract the "Winning Topic" as 'tema_principal'.
3. Identify 5-7 key words or technical concepts mentioned and put them in 'keywords'.
{subtema_instruction}5. Also include the chosen title as 'selected_title' in the output JSON.

OUTPUT FORMAT (SINGLE JSON ONLY):
{{
  "tema_principal": "Topic text",
  "selected_title": "{selected_title or ''}",
  "keywords": ["keyword1", "keyword2", ...],
  "subtemas": [
    {{
      "titulo": "Subtopic 1 Title",
      "contexto": "2-3 sentence summary of the context of this subtopic."
    }},
    {repeat_note}
  ]
}}

IMPORTANT: Return ONLY the JSON. Do not add any text before or after."""

    return plantilla.replace("[INSERTAR_ANALISIS_AQUI]", analisis_previo)
