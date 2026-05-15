from __future__ import annotations


def build_title_prompt_for_opus(script_text: str, subtemas: list[str], timeline_lines: list[str]) -> str:
    subtopics_block = "\n".join(f"- {subtema}" for subtema in subtemas) or "- No subtopics available"
    timeline_block = "\n".join(timeline_lines) or "00:00 Opening"

    return (
        "You are an elite YouTube title strategist for long-form English science documentary videos.\n\n"
        "I need title options for a documentary-style YouTube video.\n"
        "Generate exactly 12 title options in English based on the material below.\n\n"
        "Requirements:\n"
        "- English only.\n"
        "- Strong curiosity, high CTR potential, but no fake claims.\n"
        "- Sound premium, cinematic, intelligent, and documentary-driven.\n"
        "- Avoid generic titles and avoid repetition.\n"
        "- Prefer 55-72 characters when possible.\n"
        "- Make the stakes feel big, mysterious, or surprising.\n"
        "- No emojis.\n"
        "- No quotation marks around titles.\n"
        "- No explanations before the final answer.\n\n"
        "Output format:\n"
        "1. Best Title\n"
        "2. Alternate Titles\n"
        "3. Why the best one wins (1 short paragraph)\n\n"
        "Subtopics:\n"
        f"{subtopics_block}\n\n"
        "YouTube timeline:\n"
        f"{timeline_block}\n\n"
        f"Full assembled script:\n"
        f"{script_text}"
    )


def build_thumbnail_prompt_for_external_ai(
    script_text: str,
    selected_title: str,
    subtemas: list[str],
    timeline_lines: list[str],
) -> str:
    subtopics_block = "\n".join(f"- {subtema}" for subtema in subtemas) or "- No subtopics available"
    timeline_block = "\n".join(timeline_lines) or "00:00 Opening"

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
        "- If the thumbnail benefits from text overlay, include it literally in the prompt like: bold white text reading \"WORD\" in the upper left.\n"
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
        f"Subtopics:\n{subtopics_block}\n\n"
        f"Timeline:\n{timeline_block}\n\n"
        f"Full script (for visual context):\n{script_text}"
    )


def build_metadata_prompt(
    script_text: str,
    selected_title: str,
    subtemas: list[str],
    timeline_lines: list[str],
) -> str:
    subtopics_block = "\n".join(f"- {subtema}" for subtema in subtemas) or "- No subtopics available"
    timeline_block = "\n".join(timeline_lines) or "00:00 Opening"

    system = (
        "You are an expert in YouTube SEO, long-form documentary packaging, and thumbnail ideation.\n"
        "You will receive the FULL SCRIPT of an English YouTube documentary video, its chosen final title, its key subtopics, and its timeline.\n\n"
        "Your task is to return ONLY a valid JSON object with these fields:\n"
        "1. 'description_body': A polished English YouTube description body in 2 short paragraphs.\n"
        "   - The first paragraph must clearly reinforce the chosen title angle.\n"
        "   - Make it compelling, informative, and optimized for discovery.\n"
        "   - Invite the viewer to watch until the end and subscribe naturally.\n"
        "   - Do NOT include the timeline block inside this field.\n"
        "2. 'keywords': An array of 10-15 relevant English tags for this specific video.\n"
        "Return ONLY JSON in this format:\n"
        "{\n"
        "  \"description_body\": \"Description paragraphs here...\",\n"
        "  \"keywords\": [\"tag1\", \"tag2\"]\n"
        "}\n\n"
        "Do not include markdown fences. Do not include explanations."
    )

    return (
        f"{system}\n\n"
        f"CHOSEN FINAL TITLE:\n{selected_title}\n\n"
        f"SUBTOPICS:\n{subtopics_block}\n\n"
        f"YOUTUBE TIMELINE:\n{timeline_block}\n\n"
        f"FULL SCRIPT:\n{script_text}"
    )
