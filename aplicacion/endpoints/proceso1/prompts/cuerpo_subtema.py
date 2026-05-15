"""
Cuerpo Subtema Prompt — Prompt para generar el script de UN subtema del cuerpo.
Proceso 4: Se ejecuta iterativamente (una por subtema).

Translated to English.
Parte del paquete proceso1.prompts.
"""
import json
import re


def _strip_visual_references(text: str) -> str:
    """Remove image references, visual directions, and B-roll cues from research data.

    This prevents visual content from leaking into a narration-only prompt.
    Strips lines like:
      - 'Image 1: ... -> https://...'
      - '![alt](url)'
      - Lines starting with visual cues like '(show ...)', '(cut to ...)'
    """
    if not text:
        return text
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip image reference lines: "Image N: description -> URL"
        if re.match(r'^Image\s+\d+\s*:', stripped, re.IGNORECASE):
            continue
        # Skip markdown image embeds: ![alt](url)
        if re.match(r'^!\[', stripped):
            continue
        # Skip visual direction parentheticals at start of line
        if re.match(r'^\((?:show|cut to|visual|b-roll|camera|pan to|zoom)', stripped, re.IGNORECASE):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def generate_cuerpo_subtema_prompt(
    subtema_actual: dict,
    subtema_siguiente: dict | None,
    info_externa: str,
    info_interna: str,
    script_acumulado: str,
    keyword_principal: str,
    estructura: dict,
    numero_subtema: int,
    selected_title: str = "",
) -> dict:
    """
    Generates the prompt to develop ONE subtopic of the video's body.

    Args:
        subtema_actual: dict with {titulo, contexto}
        subtema_siguiente: dict with {titulo, contexto} or None
        info_externa: Deep Research for THIS subtopic
        info_interna: Internal info for THIS subtopic
        script_acumulado: Entire script generated so far (labeled with [INTRO], [BODY] tags)
        keyword_principal: Main subject
        estructura: full dict from p2_estructura
        numero_subtema: 1-N
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    titulo_actual = subtema_actual.get("titulo", "No title")
    contexto_actual = subtema_actual.get("contexto", "")

    # Global context: list of subtopics
    subtemas_all = estructura.get("subtemas", [])
    mapa_global = "\n".join(
        f'   {"→" if i + 1 == numero_subtema else " "} Part {i+1}: "{s.get("titulo", "?")}"'
        for i, s in enumerate(subtemas_all)
    )

    # -----------------------------------------------------------------------
    # Continuity section — labeled accumulated script
    # -----------------------------------------------------------------------
    if script_acumulado:
        seccion_continuidad = f"""--- CONTINUITY: ACCUMULATED SCRIPT ---
Read the LAST labeled section with special attention. Your script must continue as if it were the same person speaking without a pause. Your opening must flow seamlessly from the function of the last section — do not force a specific opening style; let the content dictate the natural transition.

[SCRIPT SO FAR]
{script_acumulado}
[END SCRIPT]

ANTI-REDUNDANCY RULE: DO NOT repeat data, figures, metaphors, or phrases that already appear in the accumulated script. If a fact was already mentioned, use a different one or delve into it from another angle."""
    else:
        seccion_continuidad = "This is the first subtopic. Start directly."

    # -----------------------------------------------------------------------
    # Transition section
    # -----------------------------------------------------------------------
    if subtema_siguiente:
        titulo_siguiente = subtema_siguiente.get("titulo", "?")
        contexto_siguiente = subtema_siguiente.get("contexto", "")
        seccion_transicion = f"""--- CLOSING TRANSITION (MANDATORY) ---
When finishing this subtopic, you must include a FINAL SENTENCE (like a question or reflection) that connects NATURALLY with the next subtopic:
   NEXT SUBTOPIC: "{titulo_siguiente}"
   CONTEXT OF THE NEXT: {contexto_siguiente}

The transition must feel like a question the viewer would naturally ask themselves after what you just told them. DO NOT use phrases like "but that's not all" or "now let's see." The question must arise from the content itself.
FORMAT: End the subtopic with 1-2 transition sentences."""
    else:
        seccion_transicion = """--- CLOSING OF THE LAST SUBTOPIC ---
This is the LAST subtopic of the body. You DO NOT need a transition.
End with a powerful reflection or a closing fact that leaves the viewer thinking.
The formal closing of the video (farewell, CTA) will be done in a separate process."""

    # -----------------------------------------------------------------------
    # Title line (North Star)
    # -----------------------------------------------------------------------
    title_line = ""
    if selected_title:
        title_line = f'VIDEO TITLE (THE PROMISE): "{selected_title}"\nREMEMBER: This section must contribute to delivering what the title promised the viewer.\n'

    # -----------------------------------------------------------------------
    # Consolidated research data (merge external + internal, strip visuals)
    # -----------------------------------------------------------------------
    info_parts = []
    if info_externa:
        info_parts.append(_strip_visual_references(info_externa))
    if info_interna:
        info_parts.append(_strip_visual_references(info_interna))
    info_section = "\n\n".join(info_parts) if info_parts else "No additional information provided."

    # -----------------------------------------------------------------------
    # Build complete prompt
    # -----------------------------------------------------------------------
    prompt_completo = f"""ROLE: Master Science Communicator Scriptwriter for YouTube. Your target audience is American (use US customary units natively: miles, feet, Fahrenheit). 
YOUR OBJECTIVE: Develop a SINGLE SUBTOPIC of the video's body. This is SUBTOPIC {numero_subtema} of {len(subtemas_all)}.

TONE & VIBE: Conversational, intellectually provocative, and slightly eerie. Do not just deliver facts; deliver a crisis of scale. Play with the viewer's perception of reality. Speak directly to "you" (the viewer). 

--- GLOBAL MAP OF THE VIDEO ---
{title_line}TOPIC: "{estructura.get("tema_principal", "?")}"
KEYWORD / SUBJECT: "{keyword_principal}"
STRUCTURE:
{mapa_global}

You are writing Part {numero_subtema}.

--- SUBTOPIC TO DEVELOP ---
TITLE: "{titulo_actual}"
CONTEXT: {contexto_actual}

--- AVAILABLE INFORMATION (ONLY FOR THIS SUBTOPIC) ---

[RESEARCH DATA]:
{info_section}

{seccion_continuidad}

ANTI-REDUNDANCY RULE: Never repeat the exact metaphors or numbers from the accumulated script. Build upon it, don't echo it.

--- STRICT WRITING INSTRUCTIONS ---

1. SCRIPT PACING (CRITICAL): This is a voiceover. People don't speak in perfect essay paragraphs. 
   - Use ellipsis (...) for dramatic pauses.
   - Use short, punchy fragments for impact. 
   - Use **bold text** to indicate vocal emphasis.
   - Do NOT use bullet points. Write continuous, fluid prose.

2. THE "MIND-BENDING" NARRATIVE:
   - Use deeply visceral, everyday analogies to make hard data feel terrifying or mind-blowing (e.g., "Imagine taking the entire Milky Way and...").
   - Frame hard data not as trivia, but as terrifyingly massive or mind-blowing concepts.
   - Your opening must continue seamlessly from the last labeled section of the accumulated script. Do not force a pattern — let the content and the function of the previous section dictate the most natural way in.

3. THE PROTAGONIST RULE:
   - The KEYWORD / SUBJECT ("{keyword_principal}") is the PROTAGONIST of the video. The entire script must revolve around it.
   - Every time you mention a secondary element (a telescope, a distance, a chemical), immediately tie it back to how it makes *the protagonist* more impressive or terrifying. 

4. YOUTUBE ANTI-CLICHÉ GUIDE:
   - Keep the flow natural. Avoid generic AI transitions like "Now", "Now then", or "As mentioned earlier".
   - Limit rhetorical questions to maximum ONE per section to maintain impact.
   - BANNED PHRASES (these sound robotic in TTS voiceover): "Picture this", "Let's start", "So let's start", "So let's begin", "Let's begin", "Imagine this", "Let me explain", "Here's the thing", "Here's the deal", "Let's dive in", "Think about it", "Consider this". Never open or transition with any of these.

5. TEXT-ONLY OUTPUT (CRITICAL):
   - Output ONLY voiceover narration text.
   - Do NOT include any visual directions, B-roll suggestions, image references, stage directions, camera cues, or on-screen text suggestions.
   - No parenthetical directions like "(show image of...)" or "(cut to...)".
   - Visuals are handled in a completely separate process.

{seccion_transicion}

OUTPUT FORMAT:
Generate 2 ALTERNATIVES of the script for this subtopic. Each alternative must have a different narrative focus and opening approach.

**ALTERNATIVA 1**
**LOCUCIÓN — Parte {numero_subtema}: {titulo_actual}**
(Narrative focus: Visceral, terrifying physical scale and feeling of insignificance. Use explosive analogies, build through the viewer's body as a reference point, make the numbers feel personal and physical. Tone: excitable, escalating "whoa" moments — Vsauce style. ~300 words)

**ALTERNATIVA 2**
**LOCUCIÓN — Parte {numero_subtema}: {titulo_actual}**
(Narrative focus: Mystery of the data and breaking of expectations. Present facts as cold evidence that stacks methodically toward an inescapable conclusion. Use precise, mathematical comparisons. Tone: contemplative, measured, "let that sink in" moments — Lemmino style. ~300 words)"""

    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
