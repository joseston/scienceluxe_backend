"""
Proceso 0 — Prompt Templates for Title & Thumbnail Generation (Pre-Production)

These prompts work WITHOUT a script — they only need the user's raw idea
and (for thumbnail) the selected title. No Gemini API calls are made here;
prompts are returned as text for the user to paste into an external AI.
"""
from __future__ import annotations


def build_title_prompt(raw_idea: str) -> str:
    """
    Generates a title-options prompt based purely on the user's raw idea.
    No script, no subtopics, no timeline — just the concept.
    """
    return (
        "You are an elite YouTube title strategist for long-form English science documentary videos.\n\n"
        "I have a VIDEO CONCEPT (not a finished script). I need title options that will define "
        "the entire creative direction of this video.\n\n"
        "VIDEO CONCEPT:\n"
        f"{raw_idea}\n\n"
        "Generate exactly 12 title options in English based on this concept.\n\n"
        "Requirements:\n"
        "- English only.\n"
        "- Strong curiosity, high CTR potential, but no fake claims.\n"
        "- Sound premium, cinematic, intelligent, and documentary-driven.\n"
        "- Avoid generic titles and avoid repetition.\n"
        "- Prefer 55-72 characters when possible.\n"
        "- Make the stakes feel big, mysterious, or surprising.\n"
        "- No emojis.\n"
        "- No quotation marks around titles.\n"
        "- No explanations before the final answer.\n"
        "- Each title must make a SPECIFIC PROMISE to the viewer about what they will learn or discover.\n"
        "- The promise must be narrow enough that someone reading the title knows EXACTLY what angle the video takes.\n\n"
        "Output format:\n"
        "1. Best Title\n"
        "2-12. Alternate Titles\n"
        "13. Why the best one wins (1 short paragraph)\n"
    )


def build_thumbnail_prompt(raw_idea: str, selected_title: str) -> str:
    """
    Generates thumbnail image-generation prompts based on the concept + chosen title.
    Same quality as Proceso 5's thumbnail prompt, but uses the raw idea
    instead of the full script for visual context.
    """
    return (
        "You are an expert at writing AI image-generation prompts (Midjourney / Stable Diffusion / Flux style).\n\n"
        "I need exactly 3 READY-TO-PASTE image-generation prompts for YouTube thumbnails.\n"
        "Each prompt must be a SINGLE block of descriptive text that I can copy and paste directly into an AI image generator. "
        "No explanations, no headers, no strategy breakdowns — just the raw prompt text.\n\n"
        "RULES FOR EACH PROMPT:\n"
        "- Write it as one continuous descriptive paragraph (the way Midjourney/Flux prompts are written).\n"
        "- Include: subject, composition, lighting, mood, color palette, camera angle, and style keywords.\n"
        "- Aspect ratio: 16:9 YouTube thumbnail format.\n"
        "- Style: photorealistic, cinematic, 8K, ultra-detailed, dramatic lighting.\n"
        "- TEXT POSITIONING IS CRITICAL — follow these rules strictly:\n"
        "  * NEVER place text in the center of the image. Always position text in a corner or along an edge.\n"
        "  * Vary the text position across prompts: upper-left, lower-right, bottom-left, top-right, etc.\n"
        "  * Split title words across different lines at different positions to create dynamic, asymmetric layouts.\n"
        "  * Example: one word anchored to the upper-left corner, a second word slightly lower and indented to the right.\n"
        "  * The text must feel like a deliberate editorial design choice, not a default centered overlay.\n"
        "  * Specify the exact corner/edge position for each word in the prompt (e.g., 'bold white text reading \"INSIDE\" anchored to the top-left corner, with \"JUPITER\" on a second line shifted slightly right').\n"
        "- Thumbnail text must be extremely short (1-4 words max) and only when it adds impact.\n"
        "- The image must feel premium, cinematic, and high-CTR — not cheap or spammy.\n"
        "- Each of the 3 prompts must be visually DIFFERENT from each other (different composition, angle, color palette, or concept).\n"
        "- Do NOT repeat the full video title as thumbnail text. Compress the core idea.\n\n"
        "OUTPUT FORMAT (exactly this, nothing else):\n\n"
        "PROMPT 1:\n[paste-ready image generation prompt here]\n\n"
        "PROMPT 2:\n[paste-ready image generation prompt here]\n\n"
        "PROMPT 3:\n[paste-ready image generation prompt here]\n\n"
        "Do NOT add any explanations, strategy notes, \"why it works\", or any other text. ONLY the 3 prompts.\n\n"
        f"Video title: {selected_title}\n\n"
        f"Video concept (for visual context):\n{raw_idea}"
    )
