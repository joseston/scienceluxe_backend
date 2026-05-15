"""
Cierre Video Prompt — Prompt para generar el cierre/despedida del video.
Subproceso 5: Se ejecuta una sola vez al final del script.

Translated to English.
Parte del paquete proceso1.prompts.
"""
import re


def generate_cierre_prompt(
    script_completo: str,
    keyword_principal: str,
    estructura: dict,
    selected_title: str = "",
) -> dict:
    """
    Generates the prompt for the video's closing (~30 sec, ~75 words).

    Args:
        script_completo: Entire accumulated script
        keyword_principal: Main subject
        estructura: full dict from p2_estructura
        selected_title: The chosen video title from Proceso 0 (the North Star).

    Returns:
        dict with prompt_completo and prompt_optimizado
    """
    tema = estructura.get("tema_principal", "?")

    # Extract last lines for continuity context
    lineas = script_completo.strip().split("\n")
    ultimas_lineas = "\n".join(lineas[-10:]) if len(lineas) > 10 else script_completo

    # Extract hook from beginning to close the narrative arc
    primeras_lineas = "\n".join(lineas[:5]) if len(lineas) > 5 else script_completo

    title_block = ""
    if selected_title:
        title_block = (
            f'VIDEO TITLE (THE PROMISE): "{selected_title}"\n'
            "The closing must make the viewer feel the video DELIVERED on what the title promised.\n"
        )

    prompt_completo = f"""ROLE: Science Communicator Scriptwriter for YouTube (Style of Veritasium, Vsauce, or Lemmino). Speaking to an American audience.
YOUR OBJECTIVE: Write the CLOSING of the video. These are the last 30 seconds. The farewell.

Tone: Direct, emotional, reflective. First person singular ("you"). No filler.

--- VIDEO CONTEXT ---
{title_block}TOPIC: "{tema}"
KEYWORD / SUBJECT: "{keyword_principal}"

--- INTRO HOOK (to close the arc) ---
{primeras_lineas}

--- LAST LINES OF THE SCRIPT (for continuity) ---
{ultimas_lineas}

--- COMPLETE SCRIPT (for anti-redundancy) ---
[COMPLETE SCRIPT]
{script_completo}
[END SCRIPT]

--- STRICT WRITING INSTRUCTIONS ---

1. LENGTH: MAXIMUM 75 WORDS (~30 seconds read aloud).
   - DO NOT write more than 80 words. This is a CLOSING, not a subtopic.
   - Every word counts. No filler, no repetitions.

2. CLOSING STRUCTURE:
   A) FINAL REFLECTION (2-3 sentences): Close the narrative arc. Connect with the emotion or question from the intro's hook. The viewer must feel that the video took them from point A to an emotional point B.
   B) SUBTLE CTA (1 sentence): Integrate the call to action INSIDE the narrative. DO NOT say "like and subscribe." Instead, connect subscribing with the topic of the video. Example: "If you want to keep exploring what lies beyond, this channel is your telescope."

3. FORBIDDEN RULES:
   - FORBIDDEN to repeat ANY data, figure, or metaphor from the script
   - FORBIDDEN to say "thanks for watching" or "see you in the next video"
   - FORBIDDEN to use lists or enumerations
   - FORBIDDEN to start with "In conclusion" or "To finish"
   - FORBIDDEN to mention the protagonist by name if they were already mentioned in the last part

4. STYLE RULES:
   - Contemplative tone, not didactic
   - The last sentence must be MEMORABLE — something the viewer remembers the next day
   - You can use a poetic image if it fits the theme
   - The CTA must feel like a natural part of the closing, not an add-on

5. NARRATIVE PROTAGONIST:
   - The closing must feel like the end of the story of "{keyword_principal}", not like a comment Section

OUTPUT FORMAT:
Generate 2 ALTERNATIVES for the closing. One more reflective, another more emotional.

**ALTERNATIVA 1** (Reflective)
**LOCUCIÓN — CIERRE**

(closing text ~75 words maximum)

**ALTERNATIVA 2** (Emotional)
**LOCUCIÓN — CIERRE**

(closing text ~75 words maximum)"""

    prompt_optimizado = re.sub(r"\s+", " ", prompt_completo).strip()

    return {
        "prompt_completo": prompt_completo,
        "prompt_optimizado": prompt_optimizado,
    }
