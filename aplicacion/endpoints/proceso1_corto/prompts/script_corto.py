"""
Script Corto — Prompt para generar el script final de un video corto.
Estructura: Gancho (3-5s) → Desarrollo (40-90s) → CTA (5-10s)
Total: ~250-350 palabras
"""


def generate_script_corto_prompt(
    estructura: dict,
    deep_research_output: str,
    info_interna_output: str,
) -> dict:
    """
    Generates the prompt to write the complete short-form video script.
    """
    tema = estructura.get('tema_principal', '')
    hook = estructura.get('angulo_hook', '')
    punto = estructura.get('punto_principal', '')
    cta = estructura.get('cta', '')
    tono = estructura.get('tono_sugerido', 'conversational')
    plataforma = estructura.get('plataforma_target', 'shorts')

    prompt_completo = f"""ROLE: You are an elite Short-Form Video Scriptwriter. You write scripts for TikTok and YouTube Shorts 
that consistently go viral. Your scripts are punchy, emotionally engaging, and impossible to scroll past.

OBJECTIVE: Write a complete script for a {plataforma.upper()} video. 
Duration: 60-90 seconds (250-350 words MAXIMUM).
Tone: {tono}

TOPIC: {tema}
PLANNED HOOK: {hook}
MAIN POINT: {punto}
PLANNED CTA: {cta}

RESEARCH (Deep Research):
{deep_research_output}

INTERNAL INFORMATION (from sources):
{info_interna_output}

SCRIPT STRUCTURE (STRICT):

=== GANCHO (0-3 seconds) ===
- The FIRST sentence must stop the scroll IMMEDIATELY
- Use the planned hook as inspiration but make it even punchier
- No greetings, no introductions — start with IMPACT
- Pattern interrupt: question, shocking stat, bold claim, or "POV:"

=== DESARROLLO (3-50 seconds) ===
- Build on the hook with the main point
- Use 2-3 strong supporting facts/examples
- Keep sentences SHORT (max 15 words each)
- Use rhetorical questions to maintain engagement
- Include at least ONE moment of surprise or revelation
- Maintain relentless pacing — no filler, no tangents
- Speak directly to the viewer ("you", "your")

=== CTA (50-60 seconds) ===
- Quick, natural call-to-action
- Connect the CTA to the content emotionally
- End with impact — the last sentence should linger

FORMATTING RULES:
1. Write the script as SPOKEN TEXT only (no stage directions, no camera notes)
2. Mark sections with === GANCHO ===, === DESARROLLO ===, === CTA ===
3. Each sentence on its own line for teleprompter readability
4. NO emojis in the script
5. Use "..." for dramatic pauses
6. Total word count: 250-350 words MAX
7. Language: Write in the same language as the source material

QUALITY CHECKLIST (verify before submitting):
- [ ] First sentence stops the scroll?
- [ ] Every sentence earns its place?
- [ ] No filler words or unnecessary transitions?
- [ ] At least 1 surprising moment?
- [ ] CTA feels natural, not forced?
- [ ] Under 350 words?"""

    prompt_optimizado = prompt_completo[:500] + "..."

    return {
        'prompt_completo': prompt_completo,
        'prompt_optimizado': prompt_optimizado,
    }
