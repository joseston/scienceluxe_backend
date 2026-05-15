"""
Proceso 4 Corto — Prompt Station Templates (Vertical 9:16)
============================================================
Same structure as P4 largo but adapted for short-form vertical video.
Aspect ratio 9:16 (1080×1920), fast-paced scenes (3–6s).
"""
from __future__ import annotations

DEFAULT_ESTILO_CANAL_CORTO = (
    "Cinematográfico, hiperrealista, 8K, estilo documental de ciencias, "
    "misterioso y grandioso, iluminación volumétrica y dramática, colores profundos, "
    "sin elementos gráficos ni texto en pantalla, FORMATO VERTICAL 9:16"
)


def build_text_to_video_prompt_corto(
    tema_principal: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
) -> str:
    dur = round(duracion_segundos, 1)
    if dur <= 3:
        speed_rule = (
            "ULTRA FAST: 'snap zoom', 'rapid push-in', 'quick whip pan'. "
            "Maximum impact in minimal time. Every frame must grip the viewer."
        )
    elif dur <= 5:
        speed_rule = (
            "FAST & DYNAMIC: 'smooth dolly forward', 'gentle orbital drift', "
            "'elegant crane up'. Fluid motion that keeps attention."
        )
    else:
        speed_rule = (
            f"MODERATE ({dur}s): 'slow pan', 'subtle zoom-out', "
            "'gentle floating descent'. Let the visual breathe."
        )

    return f"""You are an expert Prompt Engineer for AI video generation (Google VEO 3, OpenAI Sora, Runway Gen-3, Kling AI).

Your task: take the data of ONE SPECIFIC SCENE from a short-form vertical video and generate ONE HYPER-DETAILED PROMPT in English, ready to copy-paste into the AI video tool.

==== VIDEO CONTEXT ====
Topic: {tema_principal}
Visual Style: {estilo_canal}
FORMAT: VERTICAL 9:16 (1080×1920) — This is a SHORT-FORM video (TikTok/Reels/Shorts)

==== SCENE DATA ====
Duration: {dur} seconds
Visual type: {tipo_visual}
Narration: "{narracion_escena}"
Visual concept: "{concepto_visual_base}"
Physical composition: "{physical_composition}"

==== GENERATION RULES ====
1. VERTICAL FRAMING (9:16): All compositions must be designed for VERTICAL viewing. Use tight framing, center-weighted compositions, and vertical leading lines. NO horizontal cinematic widescreen framing.
2. CAMERA MOTION ({dur}s): {speed_rule}
3. MATERIAL SYNERGY: Use the visual concept as the soul of the scene. Apply physical composition as realistic textures.
4. NO TEXT: Do not describe floating text, graphics, or UI elements.
5. LIFE: Add 1-2 subtle background motion elements for depth.
6. LANGUAGE: Write the prompt ONLY in English.

==== OUTPUT FORMAT ====
Return ONLY the prompt text in English. No greetings, no explanations, no code blocks. Just the pure prompt.

==== ALTERNATIVES ====
Generate EXACTLY 3 alternative versions (OPTION 1, 2, 3), each with a slightly different visual approach. End with ✅ BEST OPTION: and why in one line."""


def build_text_to_image_prompt_corto(
    tema_principal: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
) -> str:
    return f"""You are an expert Prompt Engineer for AI image generation (Midjourney v6, Ideogram 2.0, Flux Pro).

Your task: generate TWO THINGS for ONE scene from a short-form vertical video:
1) An ultra-detailed POSITIVE PROMPT in English
2) A concise NEGATIVE PROMPT in English

==== VIDEO CONTEXT ====
Topic: {tema_principal}
Visual Style: {estilo_canal}
FORMAT: VERTICAL 9:16 (1080×1920)

==== SCENE DATA ====
Visual type: {tipo_visual}
Narration: "{narracion_escena}"
Visual concept: "{concepto_visual_base}"
Physical composition: "{physical_composition}"

==== RULES ====
1. VERTICAL 9:16 ASPECT RATIO: All compositions must be designed for VERTICAL viewing. Specify "9:16 aspect ratio, vertical portrait format" in every prompt.
2. SYNERGY: Fuse visual concept with physical composition for realistic textures.
3. TECHNICAL: Include render engine (Octane, UE5), ultra-high resolution, 9:16 vertical format.
4. COMPOSITION: Use vertical-optimized framing (center-weighted, vertical leading lines).
5. LANGUAGE: English only.

==== OUTPUT FORMAT ====
POSITIVE PROMPT:
[Full prompt in English]

NEGATIVE PROMPT:
[Always include: no text, no watermark, no logo, no UI, no blurry, no distorted, no low quality, no horizontal framing, no 16:9]

==== ALTERNATIVES ====
Generate 3 versions (OPTION 1, 2, 3), each with POSITIVE + NEGATIVE. End with ✅ BEST OPTION."""


def build_image_to_video_prompt_corto(
    tema_principal: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
) -> str:
    dur = round(duracion_segundos, 1)
    if dur <= 3:
        camera = "A quick, precise dolly-in. The main subject activates immediately."
    elif dur <= 5:
        camera = "A smooth, slow orbital drift across the frame."
    else:
        camera = f"A gentle, barely perceptible zoom out sustained over {dur} seconds."

    subject = physical_composition.strip() if physical_composition.strip() else concepto_visual_base.strip()

    return (
        f"VERTICAL 9:16 FORMAT. {camera} "
        f"Animate the physical elements: {subject}. "
        f"Slow, natural, organic motion — no sudden changes. "
        f"Background elements softly drift for depth. "
        f"Main subject gradually intensifies in brightness or motion. "
        f"Cinematic documentary feel. Volumetric lighting. "
        f"No text, no graphics, no UI elements. "
        f"IMPORTANT: Vertical portrait framing (9:16 aspect ratio)."
    )
