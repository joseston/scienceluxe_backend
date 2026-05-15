"""
Manual Hybrid Prompt Generator.

Builds the prompt that the user copies into ChatGPT during Proceso 1 / SP2
when running the architecture stage in hybrid mode without Gemini.
"""


def generate_hybrid_chatgpt_prompt(analisis_texto: str, selected_title: str = "") -> str:
    title_block = ""
    if selected_title:
        title_block = (
            f'\nCHOSEN VIDEO TITLE (THE NORTH STAR): "{selected_title}"\n'
            "NON-NEGOTIABLE RULE: both the free structure and the final 4-part structure must stay tightly aligned "
            "to the promise of this title. If a possible section does not help deliver the title, exclude it.\n"
        )

    return f"""ROLE: You are a senior YouTube narrative architect for a US science and space audience.

OBJECTIVE:
Turn the strategic analysis below into a HYBRID architecture in 2 internal phases:

PHASE A — FREE EXPANSION
- Create the best free-form narrative structure first.
- Let the story decide the number of subtopics.
- Use between 4 and 8 subtopics.
- Prioritize curiosity, escalation, visual facts, and retention.

PHASE B — COMPRESSION TO 4 MACRO-BLOCKS
- Compress the free structure into EXACTLY 4 denser macro-blocks.
- These 4 blocks must feel stronger, more cinematic, and more retention-optimized than the free structure.
- Block 1 must be the strongest viral hook.
- Blocks 2 and 3 should deepen the explanation and escalate the science.
- Block 4 should close with consequence, future impact, or the final punch.
{title_block}
INPUT: STRATEGIC ANALYSIS
{analisis_texto}

OUTPUT RULES:
1. Return ONLY valid JSON.
2. Do not add markdown fences.
3. Keep all keys exactly as written below.
4. Each "contexto" must be 2-4 sentences, concrete, and useful for later research.
5. "keywords" must contain 5 to 7 terms.
6. "estructura_final.subtemas" must contain EXACTLY 4 items.
7. Every "titulo" must be SHORT: ideally 2 to 5 words, never more than 7 words.
8. Each "titulo" must sound like a clean subtopic label, NOT like a dramatic sentence, hook, or editorial headline.
9. Put the drama, explanation, and title payoff inside "contexto", not inside "titulo".

REQUIRED JSON SHAPE:
{{
  "estructura_libre": {{
    "tema_principal": "Main topic aligned with the title",
    "selected_title": "{selected_title or ''}",
    "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
    "subtemas": [
      {{
        "titulo": "Free subtopic 1",
        "contexto": "2-4 sentence explanation of what this subtopic covers and why it matters."
      }}
    ]
  }},
  "estructura_final": {{
    "tema_principal": "Same core topic, now compressed into the final architecture",
    "selected_title": "{selected_title or ''}",
    "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
    "subtemas": [
      {{
        "titulo": "Macro-block 1",
        "contexto": "2-4 sentence explanation."
      }},
      {{
        "titulo": "Macro-block 2",
        "contexto": "2-4 sentence explanation."
      }},
      {{
        "titulo": "Macro-block 3",
        "contexto": "2-4 sentence explanation."
      }},
      {{
        "titulo": "Macro-block 4",
        "contexto": "2-4 sentence explanation."
      }}
    ]
  }}
}}

FINAL REMINDER:
Return ONLY the JSON object. No intro. No commentary. No markdown."""
