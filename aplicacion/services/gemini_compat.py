"""
Gemini compatibility layer.

Prefers the modern `google.genai` SDK when available, and falls back to
`google.generativeai` so the backend can keep working while the environment
is migrated.
"""
from __future__ import annotations


def get_sdk_label() -> str:
    try:
        from google import genai as _genai  # noqa: F401
        return "google.genai"
    except Exception:
        return "google.generativeai"


def generate_text(*, api_key: str, model: str, prompt: str) -> str:
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            return response.text or ""
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    except Exception:
        import google.generativeai as legacy_genai

        legacy_genai.configure(api_key=api_key)
        legacy_model = legacy_genai.GenerativeModel(model)
        response = legacy_model.generate_content(prompt)
        return response.text
