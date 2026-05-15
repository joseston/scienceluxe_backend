"""
URL Parser — Detecta si una URL es YouTube o Artículo.
Proceso 1, módulo core.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedURL:
    """Resultado del parseo de una URL."""
    original_url: str
    url_type: str  # "video" | "article"
    video_id: Optional[str] = None  # Solo para YouTube


# Regex para extraer el ID de YouTube (soporta múltiples formatos)
YOUTUBE_REGEX = re.compile(
    r"^.*(youtu\.be/|v/|u/\w/|embed/|watch\?v=|&v=)([^#&?]{11}).*"
)


def is_youtube_url(url: str) -> bool:
    """Verifica si una URL es de YouTube."""
    return "youtube.com" in url or "youtu.be" in url


def extract_youtube_id(url: str) -> Optional[str]:
    """Extrae el ID de 11 caracteres de una URL de YouTube."""
    match = YOUTUBE_REGEX.match(url)
    if match and len(match.group(2)) == 11:
        return match.group(2)
    return None


def parse_url(url: str) -> Optional[ParsedURL]:
    """
    Parsea una URL y determina su tipo.
    Retorna None si la URL está vacía.
    """
    url = url.strip()
    if not url:
        return None

    if is_youtube_url(url):
        video_id = extract_youtube_id(url)
        if video_id:
            return ParsedURL(
                original_url=url,
                url_type="video",
                video_id=video_id,
            )

    # Todo lo que no sea YouTube es un artículo
    return ParsedURL(
        original_url=url,
        url_type="article",
    )


def parse_urls(urls: list[str], script_id: str) -> list[dict]:
    """
    Parsea una lista de URLs y retorna una lista de dicts listos para procesar.
    """
    results = []
    for url in urls:
        parsed = parse_url(url)
        if parsed is None:
            continue

        item = {
            "script_id": script_id,
            "type": parsed.url_type,
        }

        if parsed.url_type == "video":
            item["video_id"] = parsed.video_id
        else:
            item["target_url"] = parsed.original_url

        results.append(item)

    return results
