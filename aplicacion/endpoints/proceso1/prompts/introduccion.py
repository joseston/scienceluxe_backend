"""
Introducción Prompt — Prompt para generar la intro del video.
Replica el nodo "Prompt Genera Introducción" de N8N (Proceso 3.1).

V2: Two prompt modes — "solid" (rigid formula) and "freedom" (guided creative freedom).
Translated to English.
Parte del paquete proceso1.prompts.
"""
import re


# ── PROMPT 1: ESTRUCTURA SÓLIDA (Rigid Formula) ──────────────────────────────
TEMPLATE_SOLID = """ROLE: Passionate Science Communicator (Style of Veritasium, Vsauce, or Lemmino), speaking to an American audience (use US units subtly where applicable).
YOUR OBJECTIVE: Hook the viewer in the first 5 seconds and then give them a QUICK SUMMARY (Menu) of what they will see.

YOU ARE NOT AN OLD-SCHOOL TV DOCUMENTARY NARRATOR. YOU ARE A MODERN YOUTUBER.
Tone: Direct, active, conversational (use "you," not "we" or "humanity"). Short sentences. No filler adjectives.

--- INPUT 0: THE NORTH STAR ---
{title_block}
--- INPUT 1: THE MAP (STRUCTURE TO COVER) ---
MAIN TOPIC: "{tema_principal}"
MAIN KEYWORD / SUBJECT: "{keyword}"
SUBTOPIC STRUCTURE:
{lista_subtemas}

--- INPUT 2: INFORMATION FOR THE HOOK ---
[DEEP RESEARCH DATA]:
{info_externa}

[CONTEXT DATA]:
{info_interna}

--- STRICT WRITING INSTRUCTIONS ---

1. THE VISUAL HOOK (0:00 - 0:15):
   THE GOLDEN RULE: FORBIDDEN to start telling a story in the past tense ("3 years ago..."). THAT IS SLOW.
   For the first 5 seconds, you must strictly apply this ATTENTION FORMULA:
   DEICTIC+SUBJECT → VIRAL ANCHOR → SUPERLATIVE

   A) DEICTIC + SUBJECT (Second 0-2): ALWAYS open with "This is {keyword}..." or "What you see here is {keyword}...". Direct. No beating around the bush. No mystery. The viewer must know who the protagonist is in the first 2 seconds.
      RULE: NEVER substitute "{keyword}" with indirect descriptions like "this signal," "this point," "this ship," "this data." The proper name of the subject MUST be in the first sentence.
      RULE: Never use abstract, narrative, or past-tense openings.
   B) THE VIRAL ANCHOR (Second 2-5): Immediately after naming the subject, give the viewer ONE identity fact that makes the subject viral. It must answer the question "What is so special about it?". Use the identity superlative format: "the most...", "the first...", "the only...", "the last...". This fact is what the viewer would tell a friend. Look for the MOST shocking fact you can find in the provided information or your own knowledge.
      DIVERSITY RULE: Each alternative must use a different VIRAL ANCHOR (one could say "the most distant object," another "the oldest surviving machine," another "the fastest artifact humanity has built," etc.). Do not repeat the same identity superlative.
   C) THE URGENCY SUPERLATIVE (Second 5-15): AFTER the viewer knows WHAT it is and WHY it is special, now tell them WHAT IS HAPPENING TO IT RIGHT NOW. Connect the subject with the current conflict.
      DIVERSITY RULE: Each alternative must attack a different ANGLE of the conflict (temperature, distance, isolation, death/shutdown, radiation, etc.). Do not repeat the same urgency angle between alternatives.

2. THE ESCALATION (0:15 - 0:25):
   OBJECTIVE: Reveal that the hook is just the tip of the iceberg. The viewer must go from "what a curious fact" to "I need to know more."
   FORMULA: PIVOT → DEPTH → WEIGHT → QUESTION

   A) THE PIVOT: Make the viewer feel that what they just heard in the hook is just the beginning. You can achieve this by denying, minimizing, redirecting, or reformulating the hook from an unexpected angle. The desired effect: the viewer thinking, "Wait, that's not the important part? What could be worse?".
      RULE: Never repeat the hook. Never use the same grammatical structure as the hook. Surprise with the twist.
   B) THE DEPTH: Stack 2-3 consequences or problems that are GREATER than the hook, in ascending order of severity. Each sentence must feel more serious than the last, creating a staircase of tension. Do not explain, just name them. The index will explain later.
      RULE: Use different facts than the hook. If the hook was about temperature, depth should be about radiation, distance, time, death, etc. Never repeat the angle of the hook.
   C) THE WEIGHT: Close with ONE emotional image that connects with the human experience (mortality, legacy, loneliness, insignificance, the passage of time). It is NOT another scientific fact. It is the moment where science becomes personal and the viewer feels something. Look for the sentence that lingers in the mind after closing the video.
      RULE: Each alternative must use a DIFFERENT emotional angle. If one uses "legacy," another must use "loneliness," another "mortality," another "insignificance," etc.
   D) THE QUESTION: Formulate ONE rhetorical question that summarizes all the accumulated tension. This question is the direct bridge to the Index. It must be impossible to ignore.
      RULE: Each alternative must formulate a question with a DIFFERENT focus (one about the "how," another about the "why," another about "what will happen," etc.). Do not repeat the same question structure.

3. THE "QUICK SUMMARY" INDEX (0:25 - 0:40):
   - VISUAL CONTEXT: Imagine that a STATIC IMAGE with a list of the topics (Bullet points) appears on screen.
   - INSTRUCTION: Do not narrate a complex story here. Simply LIST the topics we are going to cover so the viewer knows the menu.
   - GOLDEN RULE: Use the phrase **"In this video..."** to start the list.
   - STYLE: Fast, concise, and straight to the point.
   - STRUCTURE: Mention the subtopics fluidly but separated by commas. Each subtopic must have a brief, catchy description (not just the title).

4. THE DOOR (0:40 - 0:45):
   - STRICTLY FORBIDDEN to use cliché phrases like: "Are you ready?", "Let's begin," "Let's get to it," "Join me," "The truth is this."
   - Make a sharp transition that drops you right INSIDE the first topic, as if the video had already started. Or leave the last sentence hanging with mystery that points directly to the content of Part 1.
   - RULE: The door must feel like the first step inside a room, not the invitation to enter. Each alternative must use a DIFFERENT entry angle to Part 1.

OUTPUT FORMAT (MARKDOWN):
GENERATE 4 DISTINCT ALTERNATIVES. Each alternative must have a different creative focus across all sections. Do not repeat grammatical structures, emotional angles, or phrases between alternatives.

For each alternative use this format:

**ALTERNATIVA [N]**
**LOCUCIÓN (INTRO):**

[GANCHO — 0:00 - 0:15]
(text)

[ESCALADA — 0:15 - 0:25]
(text)

[ÍNDICE — 0:25 - 0:40]
(text)

[PUERTA — 0:40 - 0:45]
(text)"""


# ── PROMPT 2: LIBERTAD CREATIVA REAL (True Creative Freedom) ──────────────────
TEMPLATE_FREEDOM = """ROLE: You are a world-class YouTube script opener. Think Veritasium meets Lemmino meets a Netflix cold open. You write for an American audience. You understand pacing, tension, and the psychology of the first 60 seconds.

YOUR OBJECTIVE: Write a ~45-60 second introduction (~130-150 words) that is impossible to click away from. Use this space to build incredible tension and mystery.

YOU ARE NOT AN OLD-SCHOOL TV DOCUMENTARY NARRATOR. YOU ARE A MODERN YOUTUBER.
Tone: Direct, active, conversational (use "you," not "we" or "humanity"). Short sentences. No filler adjectives. Every word earns its place.

CRITICAL — THIS SCRIPT WILL BE READ BY TEXT-TO-SPEECH (TTS):
- Write ALL numbers as spoken words or natural speech: "thirty-six hundred rem" NOT "3,600 rem". "Zero point two percent" NOT "0.2%." "A hundred and six thousand miles per hour" NOT "106,000 mph."
- NEVER use symbols: no °, no %, no $, no &. Write them out as words: "degrees Fahrenheit," "percent," etc.
- Write units naturally as a person would SAY them: "minus a hundred and twenty-six degrees" NOT "-126°F."
- Avoid abbreviations: "miles per hour" not "mph." "Degrees Fahrenheit" not "°F."
- Read your script out loud in your head. If any part sounds robotic or unnatural when spoken, rewrite it.

--- INPUT 0: THE NORTH STAR ---
{title_block}
--- INPUT 1: THE MAP (STRUCTURE TO COVER) ---
MAIN TOPIC: "{tema_principal}"
MAIN KEYWORD / SUBJECT: "{keyword}"
SUBTOPIC STRUCTURE:
{lista_subtemas}

--- INPUT 2: RAW INFORMATION ---
[DEEP RESEARCH DATA]:
{info_externa}

[CONTEXT DATA]:
{info_interna}

--- THE ONLY 2 NON-NEGOTIABLES ---

You have TOTAL creative freedom on structure, pacing, and technique. There are NO mandatory sections, NO forced order, NO formulas. But these TWO INGREDIENTS must appear in every alternative:

1. THE INSTANT VIRAL HOOK (SENTENCE 1 OR 2 MAX):
   Do NOT tell a slow story. The very FIRST or SECOND sentence out of your mouth MUST deliver the VIRAL IDENTITY FACT using a superlative identity format.
   - Name the subject explicitly ("{keyword}"). Do NOT be vague.
   - The user must hear exactly what makes the subject special instantly. No rambling build-ups.
   - Each alternative MUST use a DIFFERENT viral fact. Do not repeat the same superlative.
   - FORBIDDEN OPENINGS: Do not use past-tense storytelling, imperative commands, hypothetical setups, or second-person stage directions.

2. THE CINEMATIC PROMISE (NO SPOILERS OR INFO-DUMP):
   At some point before the intro ends, build anticipation for the journey.
   - NO SPOILERS: It is strictly FORBIDDEN to summarize the structure of the video or list the subtopics. Do not explain what will happen step by step. Just establish the terrifying scope or mystery.
   - FORBIDDEN to use phrases like "In this video...", "Today we will...", or "Let's explore...". Instead, seamlessly transition into describing the scale of the journey.

--- EVERYTHING ELSE IS YOUR CALL ---

Between these 2 ingredients, you decide:
- The order and placement of each ingredient
- Whether you need escalation, emotional weight, or tension-building — or not
- Whether you go fast or slow
- Whether you end with a cliffhanger, a statement, or drop directly into the body

--- QUALITY STANDARDS ---
- CONVERSATIONAL, NOT ENCYCLOPEDIC: Do NOT stack facts like a list. A YouTube intro is a CONVERSATION, not a Wikipedia summary. If you catch yourself writing "X. And Y. And Z. And also W." — stop. Pick the ONE strongest angle and commit to it.
- Every sentence must pass the "would I say this out loud to a friend?" test. If it sounds like a textbook or a documentary narrator, rewrite it.
- No clichés. No "buckle up." No "what you're about to see will blow your mind." SHOW, don't tell.
- Vary sentence length dramatically. A 3-word sentence after a 20-word sentence creates rhythm.
- ZERO STATISTICS IN THE INTRO: It is strictly FORBIDDEN to use specific temperatures (degrees), exact distances (miles/kilometers), or dense math in the introduction. Focus on scale and emotional terror. Leave the precise numbers and textbook metrics for the body of the video.
- No transition phrases. No "let's begin." No "are you ready?" No "let's dive in."

OUTPUT FORMAT (MARKDOWN):
GENERATE 3 DISTINCT ALTERNATIVES. Each alternative must take a COMPLETELY different creative approach. Different opening technique, different structure, different pacing, different emotional angle. Surprise me.

For each alternative use this format:

**ALTERNATIVA [N]**
**LOCUCIÓN (INTRO):**

(The full intro text — no section labels, just the flowing script as it would be read aloud by TTS)"""


def generate_intro_prompt(
    estructura: dict,
    info_externa: str,
    info_interna: str,
    keyword_principal: str = "",
    selected_title: str = "",
    prompt_mode: str = "solid",
) -> dict:
    """
    Generates the Introduction prompt for the video.

    Args:
        estructura: dict with tema_principal, subtemas [{titulo, contexto}]
        info_externa: Response from Deep Research
        info_interna: Response from Info Interna
        keyword_principal: Main keyword or subject
        selected_title: The chosen video title from Proceso 0 (the North Star).
        prompt_mode: "solid" for rigid formula, "freedom" for guided creative freedom.

    Returns:
        dict with prompt_completo, prompt_optimizado, and prompt_mode
    """
    if prompt_mode not in ("solid", "freedom"):
        prompt_mode = "solid"

    # Extract data from structure
    tema_principal = estructura.get("tema_principal", "Scientific Topic")
    keyword = keyword_principal or estructura.get("keyword_principal", "the main subject")
    subtemas = estructura.get("subtemas", [])

    # Format subtopics list
    lista_subtemas = "\n".join(
        f'   - Part {i+1}: "{s.get("titulo", "?")}" (Context: {s.get("contexto", "")})'
        for i, s in enumerate(subtemas)
    )

    # Build the North Star / title block
    title_block = ""
    if selected_title:
        title_block = (
            f'CHOSEN VIDEO TITLE (THE NORTH STAR): "{selected_title}"\n'
            "CRITICAL: This is the title the viewer clicked on. The hook MUST make the viewer feel "
            "they are about to get EXACTLY what the title promised. The index MUST reinforce this promise.\n"
        )

    # Select the appropriate template
    template = TEMPLATE_SOLID if prompt_mode == "solid" else TEMPLATE_FREEDOM

    prompt_completo = template.format(
        title_block=title_block,
        tema_principal=tema_principal,
        keyword=keyword,
        lista_subtemas=lista_subtemas,
        info_externa=info_externa,
        info_interna=info_interna,
    )

    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
        "prompt_mode": prompt_mode,
    }
