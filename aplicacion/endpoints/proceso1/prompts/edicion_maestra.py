"""
Edición Maestra Prompt — Prompt para pulir y editar el guion crudo final.
Subproceso 6: Master YouTube Script Editor & Retention Specialist.

Parte del paquete proceso1.prompts.
"""
import re


def generate_edicion_maestra_prompt(guion_crudo: str, selected_title: str = "") -> dict:
    """
    Generates the master editor prompt that polishes the assembled raw script.

    Args:
        guion_crudo: The complete assembled raw script from all previous subprocesses.
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with prompt_completo and prompt_optimizado
    """

    title_block = ""
    if selected_title:
        title_block = (
            f'\nCHOSEN VIDEO TITLE: "{selected_title}"\n'
            "TITLE DELIVERY CHECK: As you edit, ensure the script delivers EXACTLY what this title promises. "
            "If any section drifts from the title's angle, flag it or tighten it.\n"
        )

    prompt_completo = f"""ROLE: Master YouTube Script Editor & Retention Specialist (Vsauce, Lemmino, Kurzgesagt style).
YOUR OBJECTIVE: Take a concatenated, multi-part script and polish it into a seamless, high-retention FINAL DRAFT. 
{title_block}
Here is the raw accumulated script:
[START RAW SCRIPT]
{guion_crudo}
[END RAW SCRIPT]

You must rewrite and format this text applying the following 5 STRICT EDITING RULES:

1. INTRODUCTION AND INDEX PRESERVATION (Non-Negotiable):
   - The introduction and its index/roadmap have already been carefully written and approved.
   - DO NOT shorten, compress, delete, reorder, or "improve" the index.
   - Preserve the intro's structure, meaning, rhythm, and full informational content.
   - Only make tiny grammar or punctuation fixes if absolutely necessary, and only when they do not change duration or intent.

2. ECHO CONTROL (Vocabulary Diversity):
   - Because this script was generated in parts, words like "terrifying," "spine," "scaffold," "impossible," and "structure" might be overused. 
   - Scan the entire text. Keep the first impactful use of a word, but find sophisticated synonyms or metaphors for subsequent uses so the vocabulary feels expansive and fresh.

3. AUDIO-VISUAL CHAPTERING (Critical for Editing):
   - There will be a 2-second visual/audio pause between the major sections of the script. 
   - DO NOT write run-on transitions that depend grammatically on the previous section (e.g., avoid starting a new section with "And that is why...").
   - Ensure the opening sentence of each new section has a **"Strong Attack"**: It must stand on its own as a powerful, declarative statement or a hook that re-engages the viewer after the pause.
   - The logic must flow, but the syntax must respect the break.
   - Remove the "=== PARTE X ===" headers.
   - Insert a standalone separator line between every major section using exactly:
     ----------------------

4. TTS-AWARE PACING & BREATHING (Controlled Formatting):
   - This script will be used for TTS/voiceover, so protect the approximate duration and do not create unnecessary pauses.
   - Break apart only truly dense "brick paragraphs" when it improves clarity or breathing.
   - DO NOT turn every sentence into its own line. Keep natural compact paragraphs whenever they read cleanly.
   - Isolate only the strongest punchlines or mind-bending reveals on their own single lines.
   - Use ellipsis (...) and **bold text** sparingly and only where the performance genuinely needs a pause or emphasis.
   - DO NOT use bullet points or numbered lists.

5. LENGTH DISCIPLINE:
   - Keep the final script close to the original word count and spoken duration.
   - Do not add new explanations, new facts, filler, or ornamental phrasing.
   - Improve flow and clarity without inflating the script.

OUTPUT FORMAT:
Return ONLY the final, polished script. Do not include any introductory or concluding remarks. Start directly with the first spoken word. Use the separator line between major sections exactly as instructed."""

    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
