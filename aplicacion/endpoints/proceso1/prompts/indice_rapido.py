"""
Índice Rápido Prompt — Prompt para generar el Mini-Índice de la Introducción.
Nuevo subproceso entre SP3 y SP4.

El Índice Rápido es un bloque de 10 segundos máximos que lista las partes del
video de forma cinematográfica. Siempre comienza con "In this video..." y
siempre termina con "Let's get started."

Solo necesita la estructura (JSON de SP2): no requiere Deep Research ni Info Interna.
Parte del paquete proceso1.prompts.
"""
import re


TEMPLATE_INDICE_RAPIDO = """ROLE: You are an aggressive trailer voiceover artist.

YOUR OBJECTIVE: Write a hyper-fast, 10-second verbal index (~20-25 words MAXIMUM).
On screen, a rapid animation will flash 4 graphics representing the 4 parts of the video. Your script is the fast-paced, punchy narration that perfectly syncs with those visual hits.

CRITICAL RULES:
1. MANDATORY OPENING: You MUST start exactly with: "In this video,"
2. THE 4 RHYTHMIC BEATS: You must quickly list the 4 parts of the journey in chronological order.
   - Keep it to 2-4 words per part.
   - Do NOT get poetic. Do NOT write long, branching sentences.
   - Just name the zones/threats rhythmically, separated by commas.
3. MANDATORY CLOSING: You MUST end exactly with: "Let's get started."

--- EXAMPLE OF THE EXACT RHYTHM DO YOU NEED TO MATCH ---
(Do not use this topic, just copy the pacing)
"In this video, we dive through the acid clouds, the gravity furnace, the metal ocean, and the missing core. Let's get started."

--- STRUCTURE TO COVER ---
MAIN SUBJECT: "{keyword}"
PARTS TO COVER:
{lista_subtemas}

OUTPUT FORMAT:
Return ONLY the final raw script. No markdown. No alternatives. No labels."""


def generate_indice_rapido_prompt(estructura: dict) -> dict:
    """
    Generates the Rapid Index prompt (bridge between cinematic intro and body).

    Args:
        estructura: dict with tema_principal, keyword_principal, subtemas [{titulo, contexto}]

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    keyword = estructura.get("keyword_principal") or estructura.get("tema_principal", "the subject")
    subtemas = estructura.get("subtemas", [])

    lista_subtemas = "\n".join(
        f"   - Part {i + 1}: {s.get('titulo', '?')}"
        for i, s in enumerate(subtemas)
    )

    prompt_completo = TEMPLATE_INDICE_RAPIDO.format(
        keyword=keyword,
        lista_subtemas=lista_subtemas,
    )

    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
