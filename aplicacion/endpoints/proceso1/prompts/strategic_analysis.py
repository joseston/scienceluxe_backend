"""
Strategic Analysis Prompt -- Generates the SP1 analysis prompt.

SP1 should stay analysis-first: understand the viral logic, the title promise,
the strongest facts, and the narrative possibilities without locking the
project into the final 4-block structure too early.
"""
import json
import re


TEMPLATE_ANALYSIS = """PROMPT FOR STRATEGIC ANALYSIS OF RAW SOURCES (PHASE 1 - ANALYSIS FIRST - US AUDIENCE)

ROLE: You are a Strategic Content Analyst and Narrative Architect for "Scieluxe", an astronomy and science channel targeting an American audience. Your job in this phase is to understand the viral logic of the topic, surface the strongest narrative opportunities, and map the best possible directions for the next structure phase.

CHOSEN VIDEO TITLE (THE NORTH STAR):
"{selected_title}"
CRITICAL: This title is already FINAL. It is the promise we made to the viewer. Your entire analysis -- hook, angle, facts, narrative possibilities, and retention logic -- must be engineered to deliver on this exact title.

INPUT DATA:
You will receive two distinct sets of data. You MUST treat them differently:
1. PRIMARY VIRAL TARGET (The trending video we are improving):
{main_video_data}

2. SUPPLEMENTARY DATA (Articles, papers, and secondary videos):
{supplementary_data}

OBJECTIVE:
1. Analyze the PRIMARY VIRAL TARGET to understand its core narrative, viral hook, pacing, and what made people click and stay.
2. Mine the SUPPLEMENTARY DATA strictly for hard facts, numbers, contradictions, and scientific context that can make our version stronger and more authoritative.
3. Keep the analysis OPEN at this stage. Do NOT lock the project into a fixed number of sections yet. That decision will happen later in the structure phase.

CRITICAL RULES:
- NEVER use metaphors, analogies, or the narrative tone from the supplementary data. Maintain the energy of a strong US YouTube science video.
- At this stage, prioritize discovery over symmetry. Surface the strongest narrative opportunities before deciding how to package them.
- You may suggest possible narrative groupings or section ideas, but DO NOT force the analysis into exactly 4 final parts.

INSTRUCTIONS:

1. HUMAN LANGUAGE TRANSLATION (THE CLARITY FILTER):
   - Focus on the PRIMARY VIRAL TARGET. Explain the core viral story in 2-3 simple, colloquial sentences, as if telling a smart friend over coffee.

2. THE VIRAL TOPIC:
   - Extract the exact topic/angle that made the PRIMARY VIRAL TARGET successful.

3. THE CLICK PROMISE:
   - Explain in 1-2 sentences what the viewer expects to receive when clicking the chosen title.

4. HOOK EXTRACTION (THE UPGRADE):
   - Extract 3-5 mind-blowing hard facts (figures, visual facts, broken records, contradictions, countdowns, turning points).
   - Pull the strongest facts from BOTH source sets, but make sure they sound punchy and usable in a viral script.

5. RETENTION LOGIC:
   - Explain which tensions, mysteries, reversals, or expectation-breaks make this topic hold attention.
   - Identify where the audience's mental model is likely wrong, incomplete, or too simplistic.

6. NARRATIVE POSSIBILITIES:
   - Suggest the most promising narrative lanes for the future structure phase.
   - You may propose candidate section ideas or clusters of ideas, but keep them flexible and do NOT force exactly 4 final parts.

MANDATORY OUTPUT FORMAT:

### 1. HUMAN LANGUAGE SUMMARY
* **The Simple Story:** [Explain the core viral story simply and directly]
* **The Viral Hook:** [What specific angle/words made the original video go viral?]

### 2. THE VIRAL TOPIC
[Topic Name (Catchy and Clear)]

### 3. THE CLICK PROMISE
* [What the viewer expects to receive from this title]

### 4. THE UPGRADE STRATEGY
* [How we can make our version stronger/more authoritative than the original]

### 5. KEY FACTS (THE UPGRADED HOOKS)
* [Fact 1 - highly visual or numerical]
* [Fact 2]
* [Fact 3]
* [Fact 4 (optional)]
* [Fact 5 (optional)]

### 6. RETENTION LOGIC
* [Belief/tension/mystery #1]
* [Belief/tension/mystery #2]
* [Belief/tension/mystery #3]

### 7. NARRATIVE POSSIBILITIES
* [Candidate lane / section idea / cluster #1]
* [Candidate lane / section idea / cluster #2]
* [Candidate lane / section idea / cluster #3]
* [Optional lane #4]
* [Optional lane #5]"""


def generate_strategic_analysis_prompt(
    main_video_data: dict,
    supplementary_data: list,
    prompt_mode: str = "freedom",
    selected_title: str = "",
) -> dict:
    """
    Generates the strategic analysis prompt.

    Args:
        main_video_data: Dict representing the primary viral target source.
        supplementary_data: List of dicts representing the remaining sources.
        prompt_mode: Preserved for compatibility, but SP1 now always uses the
            analysis-first prompt.
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with keys: prompt_completo, prompt_optimizado, prompt_mode
    """
    main_video_json = json.dumps(main_video_data, ensure_ascii=False, indent=2)
    supplementary_json = json.dumps(supplementary_data, ensure_ascii=False, indent=2)

    prompt_completo = TEMPLATE_ANALYSIS.format(
        main_video_data=main_video_json,
        supplementary_data=supplementary_json,
        selected_title=selected_title or "(No title selected yet)",
    )
    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
        "prompt_mode": "freedom",
    }
