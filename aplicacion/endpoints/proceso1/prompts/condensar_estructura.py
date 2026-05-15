"""
Condensar Estructura — Prompt texto para Claude Opus.
Condensa N subtemas libres en exactamente 4 macro-bloques narrativos.

IMPORTANTE: Esta función NO llama a ninguna API. Solo genera texto para que
el usuario lo copie y pegue en Claude Opus externamente.
"""


def generate_condensar_prompt(estructura_libre: dict, analisis_texto: str = "", selected_title: str = "") -> str:
    """
    Genera el prompt de condensación (texto plano para Opus) a partir de la
    estructura libre generada en Phase A (modo freedom).

    Args:
        estructura_libre: Diccionario con N subtemas de Phase A (modo freedom).
        analisis_texto: El contenido crudo extraído de las fuentes (Input Fuentes) —
                        transcripciones de YouTube + artículos. Es la fuente primaria de
                        hechos reales para que Opus no aluicine contenido.
        selected_title: El título del video elegido (North Star).

    Returns:
        Prompt en texto plano para copiar a Claude Opus. Sin llamada a API.
    """
    subtemas = estructura_libre.get("subtemas", [])
    tema_principal = estructura_libre.get("tema_principal", "")
    n = len(subtemas)

    subtemas_text = "\n\n".join([
        f"  SECTION {i + 1}: {st.get('titulo', '(sin título)')}\n"
        f"  Context: {st.get('contexto', '(sin contexto)')}"
        for i, st in enumerate(subtemas)
    ])

    title_block = ""
    if selected_title:
        title_block = (
            f'\nCHOSEN VIDEO TITLE (THE NORTH STAR): "{selected_title}"\n'
            "All 4 final macro-blocks MUST be engineered to deliver on this exact title's promise.\n"
        )

    analysis_block = ""
    if analisis_texto.strip():
        analysis_block = f"""
RAW SOURCE MATERIAL FROM INPUT FUENTES (YOUR FACTUAL SOURCE OF TRUTH):
This is the raw extracted content from all source URLs (YouTube transcripts and articles). Every fact, figure, and data point in your 4 macro-blocks MUST come from this material — never invent anything not present here:

{analisis_texto.strip()}

"""

    return f"""ROLE: You are the Senior Editor of "Scieluxe", a science YouTube channel. You specialize in narrative architecture for 10-minute YouTube videos that maximize viewer retention.
{title_block}{analysis_block}
MISSION: A creative AI has produced a free-form retention architecture with {n} sections for a video about "{tema_principal}". Your job is to synthesize these {n} sections into EXACTLY 4 macro-blocks that are DENSER, RICHER, and MORE POWERFUL than the originals. Use the RAW SOURCE MATERIAL above as your factual foundation — never invent facts that aren't present in those sources.

THE {n} FREE-FORM SECTIONS (YOUR BLUEPRINT — shows how the analyst grouped the ideas):
{subtemas_text}

CONDENSATION RULES:
1. You MUST produce EXACTLY 4 macro-blocks. Not 3, not 5. Exactly 4.
2. DO NOT discard any valuable content. Merge, fuse, and supercharge related ideas.
3. Each macro-block must be RICHER than the individual sections it absorbs — if you merge 2 sections into 1, the result must feel like BOTH sections fully amplified, not diluted.
4. Order by MAXIMUM RETENTION:
   - Block 1: The single strongest hook — the most counterintuitive or mind-blowing revelation. Makes the viewer feel "Wait, I was wrong this whole time?"
   - Blocks 2-3: The "how" and "why" that escalate the stakes and deepen the mystery.
   - Block 4: The closing punch — a final revelation, real-world countdown, or unanswered question that creates forward tension.
5. For each macro-block, provide:
   - A punchy, descriptive TITLE (under 10 words)
   - A CONTEXT paragraph (2-3 sentences) explaining what this block covers and why it belongs in this position.

OUTPUT FORMAT (use exactly this structure):

MACRO-BLOCK 1: [Title]
Context: [2-3 sentences explaining what this block covers and why it opens the video]

MACRO-BLOCK 2: [Title]
Context: [2-3 sentences]

MACRO-BLOCK 3: [Title]
Context: [2-3 sentences]

MACRO-BLOCK 4: [Title]
Context: [2-3 sentences]

Do NOT add any explanation, preamble, or commentary before or after these 4 macro-blocks."""
