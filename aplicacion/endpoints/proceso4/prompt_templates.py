"""
Proceso 4 — Prompt Station Templates
======================================
Pure template-builder functions.  No AI call is made here.
Each function takes the real variables from the imported P3 timeline
and injects them into a structured meta-prompt that the user will
copy and paste directly into Gemini Chat / ChatGPT / Claude.
"""
from __future__ import annotations

import re


# ─── Default channel style ────────────────────────────────────────────────────
DEFAULT_ESTILO_CANAL = (
    "Cinematográfico, hiperrealista, 8K, estilo documental de ciencias BBC/National Geographic, "
    "misterioso y grandioso, iluminación volumétrica y dramática, colores profundos (azul oscuro, "
    "dorado, negro absoluto), sin elementos gráficos ni texto en pantalla"
)

SECTIONS_ORDER = ["intro", "parte1", "parte2", "parte3", "cierre"]


def _visual_brief_value(visual_brief: dict | None, key: str) -> str:
    if not isinstance(visual_brief, dict):
        return ""
    return str(visual_brief.get(key) or "").strip()


def _format_visual_brief_section(visual_brief: dict | None) -> str:
    if not isinstance(visual_brief, dict):
        return ""

    purpose = _visual_brief_value(visual_brief, "visual_purpose")
    primary = _visual_brief_value(visual_brief, "primary_visible_subject")
    hierarchy = _visual_brief_value(visual_brief, "visual_hierarchy")
    required = _visual_brief_value(visual_brief, "required_visual_elements")
    layout = _visual_brief_value(visual_brief, "layout_constraints")
    palette = _visual_brief_value(visual_brief, "palette_lighting")
    negatives = _visual_brief_value(visual_brief, "negative_guardrails")
    if not any((purpose, primary, hierarchy, required, layout, palette, negatives)):
        return ""

    return f"""
==== VISUAL BRIEF OBLIGATORIO ====
Proposito visual: {purpose}
Sujeto visible principal: {primary}
Jerarquia visual: {hierarchy}
Elementos visuales obligatorios: {required}
Restricciones de composicion: {layout}
Paleta y luz sugeridas: {palette}
Errores visuales a evitar: {negatives}

La imagen sera incorrecta si no cumple el proposito visual, si falta un elemento visual obligatorio, o si el sujeto visible principal no se reconoce inmediatamente. Usa este brief como direccion visual minima, no como una lista rigida de posiciones exactas.
"""


def _clean_inline_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _join_prompt_clauses(*clauses: str) -> str:
    cleaned = [_clean_inline_text(clause).rstrip(" .") for clause in clauses if _clean_inline_text(clause)]
    return ". ".join(cleaned) + ("." if cleaned else "")


def _split_negative_parts(value: str | None) -> list[str]:
    raw = _clean_inline_text(value)
    if not raw:
        return []
    parts = re.split(r"[,;]+", raw)
    return [_clean_inline_text(part) for part in parts if _clean_inline_text(part)]


def _dedupe_preserve_order(parts: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(part)
    return result


# ─── Text-to-Video (VEO 3 / Sora / Runway Gen-3) ────────────────────────────
def build_text_to_video_prompt(
    tema_principal: str,
    seccion_actual: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
) -> str:
    dur = round(duracion_segundos, 1)
    if dur <= 4:
        speed_rule = (
            "Usa movimientos RÁPIDOS Y ENÉRGICOS: 'fast push-in', 'snap zoom', 'quick whip pan', "
            "'rapid aerial descent'. La cámara debe transmitir urgencia e impacto."
        )
    elif dur <= 8:
        speed_rule = (
            "Usa movimientos MODERADOS Y ELEGANTES: 'slow pan right', 'gentle dolly forward', "
            "'subtle orbital drift', 'smooth crane up'. La cámara fluye con gracia."
        )
    else:
        speed_rule = (
            f"Con {dur} segundos, usa movimientos ULTRA LENTOS E HIPNÓTICOS: "
            "'imperceptible dolly in over the full duration', 'barely perceptible zoom out', "
            "'serene floating descent', 'ultra slow drone reveal'. El tiempo parece detenerse."
        )

    return f"""Eres un Prompt Engineer experto en inteligencia artificial generativa de video (Google VEO 3, OpenAI Sora, Runway Gen-3, Kling AI).

Tu tarea: tomar los datos de UNA ESCENA específica de un documental científico y generar UN ÚNICO PROMPT HIPER-DETALLADO en inglés, listo para copiar y pegar directamente en la herramienta de IA de video.

==== CONTEXTO DEL DOCUMENTAL ====
Tema Principal del Video: {tema_principal}
Bloque / Subtema Actual: {seccion_actual}
Estilo Visual Obligatorio del Canal: {estilo_canal}

==== DATOS DE LA ESCENA A CREAR ====
Duración requerida: {dur} segundos
Tipo de visual sugerido: {tipo_visual}
Narración del locutor (lo que se escucha): "{narracion_escena}"
Concepto visual base: "{concepto_visual_base}"
Composición Física Estricta — DIBUJA EXACTAMENTE ESTO (sin magia, sin sci-fi abstracto): "{physical_composition}"

==== REGLAS DE GENERACIÓN ====

1. SINERGIA ENTRE CONCEPTO Y MATERIALIDAD (NUEVO BALANCE):
   Toma el "Concepto visual base" como el alma de la escena: respeta su FORMA, su ESCALA y su acción principal (si pide un 'filamento brillante' a gran escala, dibuja exactamente esa súper-estructura macro). Luego, usa la "Composición Física Estricta" ÚNICAMENTE como una paleta de materiales para darle texturas realistas a esa forma. Es decir: mantén la silueta de la metáfora fluida, pero descríbela construida de gases, luz, gravedad o enjambres indistinguibles, evitando el sci-fi ficticio abstracto (rayos eléctricos mágicos).

1.5 ALERTA DE ESCALA ("CUIDADO CON LAS GALAXIAS DE STOCK"):
   Las IAs de video (como VEO o Sora) se estropean y dibujan "galaxias espirales genéricas en primer plano" si en el prompt dices mucho la palabra "galaxy", arruinando el inmenso tamaño macro. Si la Composición Física exige "cúmulos de galaxias", NO las describas como discos espirales nítidos; descríbelas como "millions of glowing, indistinguishable macroscopic light nodes embedded in atmospheric deep-space fog" o similares. Mantén la escala inmensa y misteriosa.

2. CINEMATOGRAFÍA ESTRICTA:
   Describe el tipo de lente (ej. 35mm prime lens, IMAX 70mm, macro lens, anamorphic), la iluminación (volumétrica, rim-light, chiaroscuro, god rays, lens flare controlado) y las texturas de los materiales principales.

3. MOVIMIENTO DE CÁMARA SEGÚN DURACIÓN ({dur}s):
   {speed_rule}

4. CERO TEXTO LITERAL:
   No describas texto flotante, gráficos de datos, números ni UI elements a menos que el concepto base los exija explícitamente.

5. VIDA EN LA ESCENA:
   Agrega 1-2 elementos sutiles de movimiento en el fondo para dar sensación de vida y profundidad (ej. "dust particles drifting", "distant nebula slowly pulsing", "heat haze shimmer").

6. ALINEACIÓN CON EL ESTILO DEL CANAL:
   Integra de forma natural las palabras clave del Estilo Visual Obligatorio dentro del tejido de tu descripción. No las copies literalmente, intégralas.

7. IDIOMA: Escribe el prompt ÚNICAMENTE en inglés técnico cinematográfico.

==== FORMATO DE SALIDA ====
Devuelve ÚNICAMENTE el texto del prompt en inglés. Sin saludos, sin explicaciones, sin bloques de código, sin markdown. Solo el prompt puro listo para pegar en VEO 3.

==== INSTRUCCIÓN FINAL — ALTERNATIVAS ====
Genera EXACTAMENTE 3 versiones alternativas de este prompt (OPTION 1, OPTION 2, OPTION 3), cada una con un enfoque visual o de cámara ligeramente diferente pero respetando la misma escena, duración y estilo. Al final, indica claramente con la etiqueta ✅ BEST OPTION: cuál de las 3 es la mejor y por qué en una sola línea."""


# ─── Text-to-Image (Banana Pro / Midjourney / Ideogram) ─────────────────────
def build_text_to_image_prompt(
    tema_principal: str,
    seccion_actual: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
    visual_brief: dict | None = None,
) -> str:
    visual_brief_section = _format_visual_brief_section(visual_brief)
    return f"""Eres un Prompt Engineer experto en generación de imágenes con IA (Banana Pro, Midjourney v6, Ideogram 2.0, Flux Pro).

Tu tarea: tomar los datos de UNA ESCENA específica de un documental científico y generar DOS COSAS:
1) Un PROMPT POSITIVO ultra-detallado en inglés para la IA de imágenes.
2) Un PROMPT NEGATIVO conciso en inglés para excluir elementos no deseados.

==== CONTEXTO DEL DOCUMENTAL ====
Tema Principal del Video: {tema_principal}
Bloque / Subtema Actual: {seccion_actual}
Estilo Visual Obligatorio del Canal: {estilo_canal}

==== DATOS DE LA ESCENA ====
Tipo de visual sugerido: {tipo_visual}
Narración del locutor (contexto emocional): "{narracion_escena}"
Concepto visual base: "{concepto_visual_base}"
Composición Física Estricta — RENDERIZA EXACTAMENTE ESTO (sin magia, sin sci-fi abstracto): "{physical_composition}"
{visual_brief_section}

==== REGLAS DE GENERACIÓN ====

1. SINERGIA ENTRE CONCEPTO Y MATERIALIDAD (NUEVO BALANCE):
   Toma el "Concepto visual base" como el alma de la imagen: respeta su FORMA, su ESCALA y su atmósfera (si pide un 'hilo cósmico', dibuja esa súper-estructura a nivel macro). Luego, aplica la "Composición Física Estricta" a las TEXTURAS. Que los materiales sean gas brillante, niebla gravitacional, o materia cósmica hiper-realista. No ignores el concepto base, fúndelo con la ciencia física real (evitando magia o rayos eléctricos).

1.1 ANCLA PRINCIPAL DEL TITULO:
   Si el Tema Principal del Video y la Composicion Fisica Estricta comparten una entidad central (planeta, objeto, organismo, lugar o estructura), esa entidad debe permanecer visualmente reconocible. No la conviertas en contexto implicito ni la sustituyas por niebla, cristales, oscuridad, humo, gas o texturas aisladas.

1.5 ALERTA DE ESCALA MACRO ("CUIDADO CON LAS GALAXIAS DE STOCK"):
   Si la imagen es a nivel MACRO y la composición física habla de "cúmulos de galaxias", PROHÍBE que Midjourney/Flux dibujen "galaxias espirales clásicas" nítidas y detalladas en primer plano. Transforma esos cúmulos en "millions of glowing, indistinguishable macroscopic light nodes embedded in atmospheric deep-space fog" o similares. Salva la escala monumental inmensa.

2. ESPECIFICIDAD TÉCNICA: Incluye motor de renderizado implícito (Octane Render, Unreal Engine 5, V-Ray photorealistic), resolución ultra-alta (8K, ultra-high detail, sharp focus) y aspect ratio (16:9 cinematic widescreen).

3. PALETA Y LUZ: Describe la paleta de colores dominante, la dirección de la luz principal (light source angle), el tipo de sombreado (diffuse, specular, global illumination) y el mood general.

4. COMPOSICIÓN Y ENCUADRE: Define el tipo de plano (wide establishing shot, extreme close-up, medium shot, bird's eye view, low angle hero shot, etc.) y la regla de composición usada (rule of thirds, leading lines, symmetry).

5. DETALLES SENSORIALES: Describe texturas táctiles que se ven (rough, crystalline, gaseous, liquid, metallic sheen, etc.).

5.1 CONTEXTO VISIBLE OBLIGATORIO:
   Si la escena ocurre dentro, debajo o a traves de un entorno mayor, preserva ese entorno mediante horizonte, curvatura, escala, cutaway, bandas, arquitectura, superficie, silueta o contexto visual. Evita close-ups donde el entorno principal desaparezca.

6. ESTILO DEL CANAL: Integra naturalmente las palabras clave del Estilo Visual Obligatorio.

7. IDIOMA: Escribe ambos prompts ÚNICAMENTE en inglés.

==== FORMATO DE SALIDA OBLIGATORIO ====
Devuelve EXACTAMENTE en este formato (sin texto adicional antes ni después):

POSITIVE PROMPT:
[El prompt positivo completo en inglés]

NEGATIVE PROMPT:
[El prompt negativo en inglés. SIEMPRE incluir: no text, no watermark, no logo, no UI elements, no blurry, no distorted anatomy, no multiple exposure, no low quality, no stock photo look, no amateur photography, no literal abstract energy beams, no generic close-up spiral galaxies, no magical effects. Si el VISUAL BRIEF OBLIGATORIO incluye "Errores visuales a evitar", incluyelos literalmente como restricciones negativas.]

==== INSTRUCCIÓN FINAL — ALTERNATIVAS ====
Genera EXACTAMENTE 3 versiones alternativas completas de este prompt (OPTION 1, OPTION 2, OPTION 3), cada una con un encuadre, paleta de luz o composición ligeramente diferente pero respetando la misma escena y estilo del canal. Cada opción debe incluir su POSITIVE PROMPT y NEGATIVE PROMPT. Al final, indica claramente con la etiqueta ✅ BEST OPTION: cuál de las 3 es la mejor y por qué en una sola línea."""


# ─── Image-to-Video Animation (Kling / Runway / Luma Dream Machine) ──────────
def build_text_to_image_final_prompt(
    tema_principal: str,
    seccion_actual: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    physical_composition: str = "",
    visual_brief: dict | None = None,
) -> dict[str, str]:
    primary = _visual_brief_value(visual_brief, "primary_visible_subject")
    hierarchy = _visual_brief_value(visual_brief, "visual_hierarchy")
    purpose = _visual_brief_value(visual_brief, "visual_purpose")
    required = _visual_brief_value(visual_brief, "required_visual_elements")
    layout = _visual_brief_value(visual_brief, "layout_constraints")
    palette = _visual_brief_value(visual_brief, "palette_lighting")
    negative_guardrails = _visual_brief_value(visual_brief, "negative_guardrails")

    visual_type = _clean_inline_text(tipo_visual).lower()
    shot_clause = (
        "A cinematic 16:9 no-text scientific comparison or explainer image"
        if visual_type == "graphic"
        else "A cinematic 16:9 wide establishing shot"
    )
    context_clause = _join_prompt_clauses(
        shot_clause,
        f"for the documentary section {seccion_actual}",
        primary or concepto_visual_base,
    )
    action_clause = _join_prompt_clauses(
        _clean_inline_text(concepto_visual_base),
        _clean_inline_text(narracion_escena),
    )
    purpose_clause = f"Visual purpose: {purpose}" if purpose else ""
    physical = _clean_inline_text(physical_composition)
    material_clause = (
        f"Render the physical materials explicitly: {physical}, with tactile, believable textures and clear depth cues"
        if physical
        else ""
    )
    hierarchy_clause = f"Preserve the visible hierarchy exactly: {hierarchy}" if hierarchy else ""
    required_clause = f"Required visual elements: {required}" if required else ""
    layout_clause = f"Composition constraints: {layout}" if layout else ""
    palette_clause = f"Color palette and lighting: {palette}" if palette else ""
    style_clause = _join_prompt_clauses(
        "Hyperrealistic 8K science documentary look",
        "BBC / National Geographic cinematic style",
        "mysterious and grand atmosphere",
        "dramatic volumetric lighting with diffuse global illumination and controlled rim light",
        "sharp focus, ultra-high detail, 16:9 cinematic widescreen composition, no graphics, no text on screen",
    )

    positive_prompt = _join_prompt_clauses(
        context_clause,
        action_clause,
        purpose_clause,
        material_clause,
        hierarchy_clause,
        required_clause,
        layout_clause,
        palette_clause,
        "Use strong scale cues, atmospheric depth, and tactile textures that feel physically grounded",
        "For comparison, scale, process, before/after, or cause-effect scenes, make the visual relationship read first without using text, labels, arrows, charts, or UI",
        "Suggested render feel: V-Ray photorealistic lighting, Unreal Engine 5 atmospheric depth, Octane-grade material detail",
        style_clause,
    )

    negative_prompt = ", ".join(_dedupe_preserve_order([
        "no text",
        "no watermark",
        "no logo",
        "no UI elements",
        "no blurry",
        "no distorted anatomy",
        "no multiple exposure",
        "no low quality",
        "no stock photo look",
        "no amateur photography",
        "no literal abstract energy beams",
        "no generic close-up spiral galaxies",
        "no magical effects",
        "no missing required visual elements" if required else "",
        *_split_negative_parts(negative_guardrails),
    ]))
    combined_prompt = f"POSITIVE PROMPT:\n{positive_prompt}\n\nNEGATIVE PROMPT:\n{negative_prompt}"

    return {
        "text_to_image_prompt_final": combined_prompt,
        "text_to_image_positive_prompt_final": positive_prompt,
        "text_to_image_negative_prompt_final": negative_prompt,
        "source_estilo_canal": _clean_inline_text(estilo_canal),
    }


def build_text_to_animation_prompt(
    tema_principal: str,
    seccion_actual: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
    visual_brief: dict | None = None,
) -> str:
    dur = round(duracion_segundos, 1)
    primary = _visual_brief_value(visual_brief, "primary_visible_subject")
    hierarchy = _visual_brief_value(visual_brief, "visual_hierarchy")
    purpose = _visual_brief_value(visual_brief, "visual_purpose")
    required = _visual_brief_value(visual_brief, "required_visual_elements")
    layout = _visual_brief_value(visual_brief, "layout_constraints")
    palette = _visual_brief_value(visual_brief, "palette_lighting")
    negatives = _visual_brief_value(visual_brief, "negative_guardrails")
    output_bias = (
        "Graphic / scientific explainer animation"
        if _clean_inline_text(tipo_visual).lower() == "graphic"
        else "Cinematic short-form documentary animation"
    )
    return f"""You are a Prompt Engineer specialized in creating HIGH-QUALITY FINAL PROMPTS for Gemini.

Your job is to read the data of ONE scientific documentary scene and write ONE final prompt in English that will later be pasted into Gemini.

IMPORTANT:
- Do NOT create the animation itself.
- Do NOT create React / TypeScript / Remotion code.
- Do NOT return implementation notes.
- Do NOT return a concept, storyboard, or production plan directly.
- Your only task is to write the BEST possible final prompt for Gemini so Gemini can later generate the animation concept and implementation.

==== DOCUMENTARY CONTEXT ====
Main topic: {tema_principal}
Section: {seccion_actual}
Channel style: {estilo_canal}

==== SCENE DATA ====
Suggested visual type: {tipo_visual}
Target duration: {dur} seconds
Narration: "{narracion_escena}"
Base visual concept: "{concepto_visual_base}"
Animation category: {output_bias}
Physical composition that must remain present or clearly implied: "{physical_composition or concepto_visual_base}"

==== MANDATORY VISUAL BRIEF ====
Visual purpose: {purpose or "make the scene's scientific idea immediately clear"}
Primary visible subject: {primary or concepto_visual_base}
Visual hierarchy: {hierarchy or "main subject first, action second, support details third"}
Required visual elements: {required or "the concrete elements needed to understand the narration visually"}
Composition constraints: {layout or "keep the key subjects readable without over-specifying exact positions"}
Palette / lighting direction: {palette or estilo_canal}
Failure modes to avoid: {negatives or "unclear hierarchy, unreadable labels, empty background, abstract shapes without scientific meaning"}

==== WHAT YOUR FINAL GEMINI PROMPT MUST ACHIEVE ====
The final prompt you write should make Gemini produce a premium cinematic scientific animation response that is useful for production.
That final Gemini prompt should push Gemini to:
- design a strong animation concept for the exact scene
- preserve the scientific relationship, comparison, scale, process, timing, or transformation described in the narration
- choose the best motion-graphics approach when it improves clarity
- think in terms of React / TypeScript / Remotion implementation quality
- use labels, gauges, arrows, overlays, maps, counters, guides, diagrams, waveforms, or markers only when they genuinely help understanding
- avoid clutter, generic dashboard aesthetics, unreadable UI overload, and decorative motion with no explanatory value
- keep the result cinematic, elegant, readable, and documentary-grade

==== WHAT THE FINAL GEMINI PROMPT SHOULD USUALLY ASK FOR ====
The final prompt you generate should usually instruct Gemini to return:
1. a short creative description of the animation
2. a complete TypeScript/React/Remotion-style code example
3. brief notes explaining timing and implementation logic
4. any assumptions made

==== OUTPUT FORMAT YOU MUST FOLLOW ====
Return ONLY the final prompt that will be pasted into Gemini.
No greetings.
No explanations.
No markdown fences.
No multiple options.
No commentary before or after.
Just the final prompt text, ready to copy and paste into Gemini."""


def build_image_to_video_prompt(
    tema_principal: str,
    seccion_actual: str,
    estilo_canal: str,
    narracion_escena: str,
    concepto_visual_base: str,
    tipo_visual: str,
    duracion_segundos: float,
    physical_composition: str = "",
) -> str:
    dur = round(duracion_segundos, 1)

    # Camera movement based on duration
    if dur <= 4:
        camera = "A quick, precise dolly-in. The main subject activates immediately."
    elif dur <= 8:
        camera = "A smooth, slow orbital drift across the frame."
    else:
        camera = (
            "An ultra-slow, barely perceptible zoom out sustained over the full "
            f"{dur}-second clip. Time appears to stand still."
        )

    # What to animate (use physical_composition if available, else fall back to concept)
    subject = physical_composition.strip() if physical_composition.strip() else concepto_visual_base.strip()

    return (
        f"{camera} "
        f"Animate the physical elements present in the image: {subject}. "
        f"They move with slow, natural, organic motion — no sudden changes. "
        f"Background: distant elements softly drift or pulse to give depth and life. "
        f"The main subject gradually intensifies in brightness or motion across the clip. "
        f"Cinematic BBC/National Geographic documentary feel. "
        f"Deep black void. Volumetric lighting. No text, no graphics, no UI elements."
    )
