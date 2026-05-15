"""
Introducción Ensamblaje — Prompt para unificar las mejores secciones seleccionadas.
Ronda 2 del proceso de Introducción.

Translated to English.
Parte del paquete proceso1.prompts.
"""


def generate_ensamblaje_prompt(
    gancho_seleccionado: str,
    pregunta_seleccionada: str,
    peso_seleccionado: str = "",
    indice_seleccionado: str = "",
    puerta_seleccionada: str = "",
) -> dict:
    """
    Generates the Assembly prompt (Round 2) for the Introduction.

    Args:
        gancho_seleccionado: EXACT text
        pregunta_seleccionada: question text
        peso_seleccionado: weight text
        indice_seleccionado: index text
        puerta_seleccionada: door text

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    # Weight
    if peso_seleccionado:
        seccion_peso = f"""[SELECTED EMOTIONAL ANGLE / WEIGHT]:
{peso_seleccionado}"""
    else:
        seccion_peso = """[EMOTIONAL ANGLE / WEIGHT]:
None selected. Generate 4 DIFFERENT and powerful emotional angles for each alternative (mortality, legacy, loneliness, insignificance, oblivion, etc.)."""

    # Index
    if indice_seleccionado:
        seccion_indice = f"""[SELECTED INDEX]:
{indice_seleccionado}"""
    else:
        seccion_indice = """[INDEX]:
None selected. Generate an index that lists the 4 subtopics of the video fluidly and catchily."""

    # Door
    if puerta_seleccionada:
        seccion_puerta = f"""[SELECTED DOOR]:
{puerta_seleccionada}"""
        instruccion_puerta = """4. THE DOOR: Use the selected door as a BASE. Generate variations that maintain the same entry angle but with different phrasing."""
        formato_puerta = """
[PUERTA — 0:40 - 0:45]
(text)"""
    else:
        seccion_puerta = """[DOOR]:
No door needed. The video transitions directly from the index to the body (Part 1)."""
        instruccion_puerta = """4. THE DOOR: DO NOT generate a door. The script ends at the index. After the index, the body of the video begins directly."""
        formato_puerta = ""

    prompt_completo = f"""ROLE: High-Impact YouTube Scriptwriter. Target audience is American.
YOUR OBJECTIVE: Take the BEST SECTIONS selected from 4 previous alternatives and assemble them into UNIFIED, fluid introductions.

Tone: Direct, active, conversational (use "you," not "we" or "humanity"). Short sentences. No filler adjectives.

--- CONTEXT ---
In Round 1, 4 introduction alternatives were generated for a YouTube video.
The user has selected the BEST SECTIONS from different alternatives.
Your job is to UNIFY them into a script that flows as if it were written all at once in fluent, engaging English.

--- SELECTED SECTIONS ---

[SELECTED HOOK (UNTOUCHABLE)]:
{gancho_seleccionado}

[SELECTED RHETORICAL QUESTION]:
{pregunta_seleccionada}

{seccion_peso}

{seccion_indice}

{seccion_puerta}

--- STRICT ASSEMBLY INSTRUCTIONS ---

1. THE HOOK: Use EXACTLY the selected hook. Do not modify it, do not rewrite it. It is untouchable. Copy it exactly as is.

2. THE ESCALATION: This is the section you must CREATE from scratch for each alternative.
   FORMULA: PIVOT → DEPTH → WEIGHT → QUESTION

   A) THE PIVOT: Must react DIRECTLY to the selected hook. Make the viewer feel that the hook is just the beginning. You can deny, minimize, redirect, or reformulate from an unexpected angle.
      RULE: Never repeat the hook. Each alternative must use a DIFFERENT pivot twist.

   B) THE DEPTH: Stack 2-3 consequences that are GREATER than the hook, in ascending order of severity. Use facts different from the hook.
      RULE: Each alternative must choose DIFFERENT FACTS to stack.

   C) THE WEIGHT: Close with ONE emotional image that connects with the human experience. If an emotional angle was provided above, keep THAT angle but express it with DIFFERENT words in each alternative. If not provided, generate a DIFFERENT emotional angle for each alternative.
      RULE: Same underlying emotion (if selected), different expression every time.

   D) THE QUESTION: Use the selected rhetorical question as a BASE. Generate natural variations that maintain the same tension and focus. Do not copy it verbatim in all alternatives.

3. THE INDEX: If one was provided, use it as a BASE with minimal stylistic variations. If not, generate one that lists the 4 subtopics fluidly and catchily. Always start with "In this video...".

{instruccion_puerta}

5. MASTER FLUIDITY RULE: The complete script must sound as if A SINGLE PERSON wrote it straight through. It cannot feel like pasted pieces. Transitions between sections must be natural.

OUTPUT FORMAT (MARKDOWN):
GENERATE 4 assembly ALTERNATIVES. Each must feel different in pace and tone, but they all use the same base hook and question.

For each alternative use this format:

**ALTERNATIVA [N]**
**LOCUCIÓN (INTRO):**

[GANCHO — 0:00 - 0:15]
(text)

[ESCALADA — 0:15 - 0:25]
(text)

[ÍNDICE — 0:25 - 0:40]
(text){formato_puerta}"""

    import re
    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
