"""
Deep Research Prompt — Prompt final para investigación profunda externa.
Replica el nodo "Prompt de Deep Research" de N8N.

Translated to English.
Parte del paquete proceso1.prompts.
"""
import json


def generate_deep_research_prompt(estructura: dict, selected_title: str = "") -> dict:
    """
    Generates the Deep Research prompt from the JSON structure.

    Args:
        estructura: dict with tema_principal, keywords, subtemas
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    # Minifier
    json_minified = json.dumps(estructura, ensure_ascii=False, separators=(",", ":"))

    title_block = ""
    if selected_title:
        title_block = (
            f'\n**CHOSEN VIDEO TITLE (THE NORTH STAR):** "{selected_title}"\n'
            "**TITLE ALIGNMENT RULE:** Prioritize facts, visuals, and data that directly help deliver "
            "on this title's promise. If a fact doesn't serve the title's angle, deprioritize it.\n"
        )

    plantilla = f"""# DEEP RESEARCH MISSION: CONTENT AND VISUAL EVIDENCE

**ROLE:** You are the Head of Research and Documentation for "Scienceluxe", an astronomy and science channel targeting an American audience. You have access to deep search tools.
{title_block}
**OBJECTIVE:** You will receive an outline of a viral scientific topic. Your mission is twofold:
1. Validate the facts with hard data.
2. Locate **OFFICIAL VISUAL EVIDENCE** (Real images from space agencies/observatories, not generic photos).

**STRATEGIC INPUT (JSON):**
[PEGAR_AQUI_EL_JSON_GENERADO_EN_EL_PASO_ANTERIOR]

**EXECUTION INSTRUCTIONS (DEEP RESEARCH):**

Analyze the JSON and run a deep research for **EACH** subtopic in the structure. Report the following:

1.  **🔎 The Scientific Truth (Fact-Check):**
    * Find the technical explanation in official papers or press releases. Adjust context for a US audience if necessary (e.g. equivalents in miles, Fahrenheit, etc. when applicable, though focus first on getting the hard facts).

2.  **🎣 Viral Angle vs. Reality:**
    * Contrast the "clickbait" (what they say on YouTube) with the scientific reality.

3.  **💎 Golden Data (The Ammo):**
    * Find 3 hard facts (figures, exact dates, distances in miles/lightyears or relevant units) that enrich the script.

4.  **📸 VISUAL EVIDENCE HUNT (CRITICAL - OFFICIAL SOURCES ONLY):**
    * **OBJECTIVE:** I need the links to REAL images or graphics related to this subtopic.
    * **STRICT FILTER:** Search **ONLY** in authority domains: NASA (.gov), ESA (.int), JAXA, Observatories (ESO, ALMA), Universities (.edu) or official instrument accounts (e.g., official @NASAWebb Twitter).
    * **FORBIDDEN:** Do not give me stock images, generative AI, Pinterest, or thumbnails from other YouTubers.
    * **FORMAT:** Briefly describe the image and provide the **DIRECT LINK** to the official source.

**REPORT DELIVERY FORMAT:**

Use Markdown. Structure the response by Subtopic.

For each subtopic, use this outline:
* **Consensus:** ...
* **Key Facts:** ...
* **Viral vs Real:** ...
* **📂 OFFICIAL VISUAL RESOURCES:**
    * *Image 1:* [Brief description] -> [OFFICIAL DIRECT LINK]"""

    prompt_completo = plantilla.replace(
        "[PEGAR_AQUI_EL_JSON_GENERADO_EN_EL_PASO_ANTERIOR]", json_minified
    )

    # Optimized version
    import re
    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
