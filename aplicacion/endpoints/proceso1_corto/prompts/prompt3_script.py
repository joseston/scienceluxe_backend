"""
Prompt 3 — Final Script: Genera el prompt final para crear el script del video corto.
Optimizado para TTS (Text-to-Speech) y retención en videos de 1 minuto.
"""


def generate_script_prompt(main_idea: str, information: str, introduction: str) -> str:
    """
    Step 3: Genera el prompt final completo.
    El usuario lo copia y pega en ChatGPT/Gemini para obtener el script.
    """
    return f'''ROLE: You are an elite short-form video scriptwriter. You write 1-minute narration scripts for TTS (Text-to-Speech) audio that go viral on YouTube Shorts and TikTok. Your scripts are punchy, fast-paced, and impossible to scroll past.

OBJECTIVE: Write a 1-minute narration script for TTS audio about the following topic. The script must resonate with an American audience.

TOPIC: "{main_idea}"
INTRODUCTION SENTENCE: "{introduction}"

ADDITIONAL INFORMATION (raw research — must be reformulated):
("{information}")

--- SCRIPT STRUCTURE (STRICT) ---

1. VIRAL FACT CHAIN: Structure the script as a RAPID SEQUENCE of impactful facts. Each sentence must feel like an independent viral statement that hooks into the next one. Think of it as a chain where every link is a "wow" moment — NOT a traditional narrative or essay.

2. OPENING: The script MUST start with the exact INTRODUCTION SENTENCE provided above. DO NOT modify it in any way.

3. FACT SELECTION: Pick the 3 to 5 most shocking, shareable facts from the ADDITIONAL INFORMATION. Do NOT try to include everything. Only use facts that would make someone stop scrolling and say "wait, what?"

4. CLOSING — DROP THE MIC: The last sentence must be a powerful, memorable statement that hits like a punchline. It should be the kind of line someone would quote or share with a friend. Make it land hard.

--- TTS AUDIO OPTIMIZATION (CRITICAL) ---

This script will be read by an AI voice (TTS), NOT a human narrator. This changes everything:

1. SENTENCE LENGTH: Maximum 15 words per sentence. Short sentences sound punchy and clear in TTS. Long sentences sound robotic and boring.

2. PACING: Maintain a fast, relentless rhythm. Every sentence must push the viewer forward to the next one. No pauses, no filler, no "let me explain" moments. Each line earns its place or gets cut.

3. SPEAKABILITY: Every word must sound natural when spoken aloud by a synthetic voice. Read each sentence in your head — if it sounds awkward, rewrite it.

--- FORBIDDEN RULES (STRICT) ---

1. FORBIDDEN: Specific years or dates. NEVER say "In 1994" or "Back in 2003." Instead, describe the event without the date: "A comet once slammed into Jupiter" instead of "In 1994, Comet Shoemaker-Levy 9 slammed into Jupiter."

2. FORBIDDEN: Hard-to-pronounce names of comets, missions, spacecraft, scientists, or technical terms. Replace them with short, colloquial descriptions. Say "the biggest nuke ever tested" instead of "the Tsar Bomba." Say "a comet" instead of "Comet Shoemaker-Levy 9." Say "NASA crashed a probe into Jupiter" instead of "NASA deliberately crashed the Galileo spacecraft."

3. FORBIDDEN: Academic or encyclopedic language. This is NOT a documentary. This is a viral TTS video. Write like you are telling a shocking fact to a friend, not reading from a textbook.

4. FORBIDDEN: Scene directions, transitions, visual cues, tone annotations like [Triumphant], [Reflective], or any formatting marks.

5. FORBIDDEN: Filler phrases and generic transitions. Never use "But here is the thing," "Now let us talk about," "As it turns out," "Interestingly enough," "What is even crazier," or any similar filler.

6. FORBIDDEN: Starting sentences with "So" or "Now." These kill momentum in TTS audio.

7. FORBIDDEN: Complex compound sentences with multiple commas. Break them into two or three short punchy sentences.

--- REFORMULATION RULE (CRITICAL) ---

Do NOT copy facts from the ADDITIONAL INFORMATION word-for-word. REFORMULATE every single fact into the most viral, easy-to-listen, TTS-friendly version possible. Strip out technical names, dates, and jargon. Keep the shock value, lose the textbook tone.

--- OUTPUT FORMAT ---

Provide ONLY the script as continuous text. No headers, no labels, no section markers, no annotations. Just the spoken words from first sentence to last sentence. Nothing else.

--- EXAMPLE OF THE STYLE ---

(This is what would happen if the Sun disappeared right now. Earth would not go dark instantly. You would still see sunlight for eight full minutes. Then total darkness. The temperature would start dropping immediately. Within a week, the entire planet would be below zero. Oceans would freeze from the surface down. But here is the worst part. Without the Sun is gravity, Earth would fly off into space in a straight line. No orbit. No destination. Just a frozen rock drifting through the void forever. And you would never even know which direction you were heading.)

Note: The example above shows the exact style and format expected. Short sentences. Viral facts. No names or dates. TTS-friendly. Continuous text only.'''
