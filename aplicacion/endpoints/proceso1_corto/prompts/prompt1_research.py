"""
Prompt 1 — Research: Buscar facts virales sobre la idea principal.
Exactamente igual al flujo probado de short_video_window.py
"""


def generate_research_prompt(main_idea: str) -> str:
    """
    Step 1: Genera el prompt de investigación.
    El usuario lo copia y pega en ChatGPT/Gemini para obtener los facts.
    """
    return (
        f'Research and compile a list of the most viral and widely-discussed facts '
        f'about "{main_idea}". The information should be sourced from multiple '
        f'reputable sources and formatted in a way that can be easily '
        f'incorporated into a script.'
    )
