"""
Prompt 2 — Introduction: Generar 6 alternativas de introducción.
Exactamente igual al flujo probado de short_video_window.py
"""


def generate_introduction_prompt(main_idea: str, information: str) -> str:
    """
    Step 2: Genera el prompt para obtener 6 alternativas de introducción.
    El usuario lo copia y pega en ChatGPT/Gemini.
    """
    return (
        f'I need to create a good introduction for a video script '
        f'So, I would like that you help me. '
        f'I have a Idea: "{main_idea}" '
        f'but I need to refine this to people retention. '
        f'So the Introduction must be the better. '
        f'Here are some information for this introduction : ( {information} ) '
        f'Please give me a list of 6 alternatives for the introduction based on the Idea, '
        f'the introduction should be shorts, it\'s a introduction for a video of 1 minute '
        f'so the introduction must have 5-10 secs aprox. '
        f'Please also dont include in the final part (lets explore, join us, lets dive).'
    )
