"""
Deep Research — Prompt de investigación profunda para videos cortos.
Versión compacta enfocada en un solo ángulo/punto principal.
"""


def generate_deep_research_prompt(estructura: dict) -> dict:
    """
    Generates the deep research prompt for a short-form video.
    Focuses research on ONE angle instead of 4 subtopics.
    """
    tema = estructura.get('tema_principal', '')
    hook = estructura.get('angulo_hook', '')
    punto = estructura.get('punto_principal', '')
    keywords = estructura.get('keywords', [])
    keywords_str = ', '.join(keywords) if keywords else 'N/A'

    prompt_completo = f"""ROLE: You are a Research Assistant specialized in short-form video content for TikTok and YouTube Shorts.

OBJECTIVE: Provide focused, deep research on ONE specific angle of a topic.
This research will be used to write a 60-90 second video script (approx. 250-350 words).
The research must be CONCISE but POWERFUL — every fact must earn its place.

TOPIC: {tema}
VIRAL HOOK: {hook}
MAIN POINT: {punto}
KEYWORDS: {keywords_str}

RESEARCH REQUIREMENTS:

1. **HOOK AMMUNITION** (3-5 facts/stats that make the hook irresistible)
   - Surprising statistics
   - Counterintuitive facts
   - "Did you know..." type revelations

2. **CORE EVIDENCE** (for the main point — 2-3 strong supporting facts)
   - Real data, studies, or examples
   - Expert quotes if available
   - Before/after comparisons

3. **VIRAL ELEMENT** (what makes this shareable?)
   - Emotional trigger
   - Social currency (makes the sharer look smart/informed)
   - Practical value

4. **QUICK CONTEXT** (2-3 sentences of background the viewer needs)
   - Just enough context so the viewer understands
   - No lengthy history — this is a short video

IMPORTANT RULES:
- Keep the total research under 800 words
- Prioritize SURPRISING facts over comprehensive coverage
- Every piece of information should serve the hook or the main point
- Think: "Will this make someone stop scrolling?" If no, cut it.

Format: Plain text, organized by the sections above."""

    prompt_optimizado = prompt_completo[:500] + "..."

    return {
        'prompt_completo': prompt_completo,
        'prompt_optimizado': prompt_optimizado,
    }


def generate_info_interna_prompt(estructura: dict, datos_crudos: str) -> dict:
    """
    Generates the internal info prompt for short-form video.
    Extracts the most relevant nuggets from source material.
    """
    tema = estructura.get('tema_principal', '')
    hook = estructura.get('angulo_hook', '')
    punto = estructura.get('punto_principal', '')

    prompt_completo = f"""ROLE: You are a Content Curator for short-form video scripts.

OBJECTIVE: From the raw source material below, extract ONLY the most impactful information 
that supports our specific hook and main point. We're writing a 60-90 second video, so we 
need only the BEST nuggets — no filler.

TOPIC: {tema}
HOOK: {hook}
MAIN POINT: {punto}

RAW SOURCE MATERIAL:
{datos_crudos}

EXTRACT THE FOLLOWING:

1. **TOP 3 QUOTES/FACTS** that directly support the hook
2. **BEST EXAMPLE or STORY** (max 3 sentences) that illustrates the main point
3. **SURPRISING DATA POINT** that could go viral on its own
4. **EMOTIONAL MOMENT** — the most human/relatable element from the sources

RULES:
- Maximum 500 words total
- Only extract what's DIRECTLY relevant to our hook and main point
- If the source material is weak on a point, say so rather than padding
- Prioritize specificity over generality (exact numbers > vague claims)

Format: Plain text, organized by the sections above."""

    prompt_optimizado = prompt_completo[:500] + "..."

    return {
        'prompt_completo': prompt_completo,
        'prompt_optimizado': prompt_optimizado,
    }
