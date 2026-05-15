"""
Info Interna Prompt — Prompt final para redacción con datos internos.
Replica el nodo "Prompt Información Interna" de N8N.

Translated to English.
Parte del paquete proceso1.prompts.
"""
import re


def generate_info_interna_prompt(estructura: dict, datos_crudos_texto: str, selected_title: str = "") -> dict:
    """
    Generates the Internal Info prompt combining
    the AI structure + P1 transcripts/articles.

    Args:
        estructura: dict with subtemas [{titulo, contexto}, ...]
        datos_crudos_texto: concatenated text of all P1 sources
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    subtemas = estructura.get("subtemas", [])

    # Generate structure instructions
    instrucciones = []
    for sub in subtemas:
        instrucciones.append(
            f'### REQUIRED SECTION: "{sub.get("titulo", "No title")}"\n'
            f'CONTEXT/FOCUS: {sub.get("contexto", "No context")}'
        )
    instrucciones_texto = "\n\n".join(instrucciones)
    num_subtemas = len(subtemas)

    title_block = ""
    if selected_title:
        title_block = (
            f'\nCHOSEN VIDEO TITLE (THE NORTH STAR): "{selected_title}"\n'
            "TITLE ALIGNMENT RULE: Every section you write must contribute to delivering "
            "on this title's promise. Prioritize data and facts that serve the angle of the title.\n"
        )

    prompt_completo = f"""ROLE: You are a Senior Science Writer and Data Analyst.
OBJECTIVE: Write a detailed research report STRICTLY following the provided structure. Target an American audience (use appropriate measurements subtly where it makes sense).
{title_block}
INPUT 1: WRITING STRUCTURE (MANDATORY)
You must generate content ONLY for these {num_subtemas} subtopics defined by the strategy. Use the context to guide the focus of each paragraph:

{instrucciones_texto}

INPUT 2: RESEARCH MATERIAL (RAW DATA)
Use the information from these transcripts to fill the subtopics with hard data, telescope names, exact dates, and figures:

[DATA START]
{datos_crudos_texto}
[DATA END]

OUTPUT INSTRUCTIONS:
1. Generate ONLY the {num_subtemas} sections requested in Input 1.
2. Format: Use Markdown with H3 headers (###).
3. Style: Long, dense, and narrative paragraphs (Long-form). DO NOT USE LISTS OR BULLET POINTS.
4. If information is missing in the raw data for any point, use your logic to connect the available facts based on the context.

EXPECTED FINAL FORMAT:

### [Subtopic 1 Title]
(Dense and detailed text...)

### [Subtopic 2 Title]
(Dense and detailed text...)
..."""

    # Optimized version
    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
