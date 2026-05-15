"""
Strategic Analysis — Prompt para videos cortos (TikTok/YouTube Shorts).
Adapta el análisis estratégico para encontrar el mejor ángulo/hook
para un video de máximo 2 minutos.
"""


def generate_strategic_analysis_prompt(main_video_data: dict, supplementary_data: list[dict]) -> dict:
    """
    Generates a strategic analysis prompt optimized for short-form video content.
    Instead of finding 4 subtopics, we focus on finding the single most viral angle.
    """

    # Build source block
    source_blocks = []
    if main_video_data:
        source_blocks.append(
            f"=== FUENTE PRINCIPAL ===\n"
            f"Título: {main_video_data.get('titulo', 'Sin título')}\n"
            f"Tipo: {main_video_data.get('tipo', 'unknown')}\n"
            f"Contenido:\n{main_video_data.get('texto', '')}\n"
        )

    for i, sup in enumerate(supplementary_data, start=2):
        source_blocks.append(
            f"=== FUENTE {i} ===\n"
            f"Título: {sup.get('titulo', 'Sin título')}\n"
            f"Tipo: {sup.get('tipo', 'unknown')}\n"
            f"Contenido:\n{sup.get('texto', '')}\n"
        )

    all_sources = "\n".join(source_blocks)

    prompt_completo = f"""ROLE: You are a Short-Form Video Strategist specialized in TikTok and YouTube Shorts.

OBJECTIVE: Analyze the provided source material and identify the SINGLE MOST VIRAL angle for a 
short-form video (30 seconds to 2 minutes maximum). Unlike long-form videos, short videos need 
ONE powerful hook, ONE clear point, and ONE call-to-action.

SOURCE MATERIAL:
{all_sources}

YOUR ANALYSIS MUST INCLUDE:

1. **VIRAL HOOK** (the most attention-grabbing opening line — must stop the scroll in 3 seconds)
   - Write 3 alternative hooks ranked by viral potential
   - Each hook should be provocative, surprising, or counterintuitive

2. **SINGLE CORE INSIGHT** (the ONE thing the viewer will learn/feel)
   - What is the most shareable, surprising, or useful insight from this material?
   - Why would someone share this with a friend?

3. **EMOTIONAL ANGLE** (curiosity, shock, FOMO, inspiration, humor)
   - Which emotion drives the highest engagement for this specific topic?

4. **TARGET AUDIENCE** (who would stop scrolling for this?)
   - Primary demographic and interest

5. **RECOMMENDED STRUCTURE** (for 60-90 second video):
   - Hook (0-3s): Stop the scroll
   - Context (3-10s): Why should they care?
   - Main Point (10-50s): The core content
   - Payoff/CTA (50-60s): What to do next

6. **KEYWORD PRINCIPAL**: The main keyword/topic for SEO and research.

Format your response as a detailed strategic analysis in plain text.
Be specific and actionable — this will be used to write the actual script."""

    # Optimized version (shorter, for quick copy)
    prompt_optimizado = prompt_completo[:500] + "..."

    return {
        'prompt_completo': prompt_completo,
        'prompt_optimizado': prompt_optimizado,
    }
