"""
YouTube Extractor — Extrae transcripts de videos de YouTube.
Proceso 1, módulo core.
"""
import logging
import os
import re
import urllib.request
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeRequestFailed,
)
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig


logger = logging.getLogger(__name__)


def get_video_title(video_id: str) -> str:
    """Extrae el título del video desde la página de YouTube."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        html = urllib.request.urlopen(url).read().decode("utf-8")
        match = re.search(r"<title>(.*?)</title>", html)
        if match:
            title = match.group(1).replace(" - YouTube", "").strip()
            return title
    except Exception:
        pass
    return f"Video {video_id}"


def _first_env(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or '').strip()
        if value:
            return value
    return ''


def _build_proxy_config():
    webshare_username = _first_env('YOUTUBE_WEBSHARE_PROXY_USERNAME', 'WEBSHARE_PROXY_USERNAME')
    webshare_password = _first_env('YOUTUBE_WEBSHARE_PROXY_PASSWORD', 'WEBSHARE_PROXY_PASSWORD')
    if webshare_username and webshare_password:
        locations_raw = _first_env('YOUTUBE_WEBSHARE_PROXY_LOCATIONS', 'WEBSHARE_PROXY_LOCATIONS')
        retries_raw = _first_env('YOUTUBE_WEBSHARE_RETRIES', 'WEBSHARE_PROXY_RETRIES')
        locations = [item.strip().lower() for item in locations_raw.split(',') if item.strip()]
        try:
            retries = int(retries_raw) if retries_raw else 10
        except ValueError:
            retries = 10
        logger.info("[P1] YouTube transcript extractor using Webshare proxy config")
        return WebshareProxyConfig(
            proxy_username=webshare_username,
            proxy_password=webshare_password,
            filter_ip_locations=locations or None,
            retries_when_blocked=max(retries, 0),
        )

    http_proxy = _first_env('YOUTUBE_HTTP_PROXY', 'HTTP_PROXY', 'http_proxy')
    https_proxy = _first_env('YOUTUBE_HTTPS_PROXY', 'HTTPS_PROXY', 'https_proxy')
    if http_proxy or https_proxy:
        logger.info("[P1] YouTube transcript extractor using generic proxy config")
        return GenericProxyConfig(
            http_url=http_proxy or None,
            https_url=https_proxy or None,
        )

    return None


def _build_youtube_api() -> YouTubeTranscriptApi:
    proxy_config = _build_proxy_config()
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def _short_youtube_error(exc: Exception) -> str:
    if isinstance(exc, (RequestBlocked, IpBlocked)):
        return (
            "YouTube bloqueó la extracción del transcript para esta IP/proxy. "
            "Si usas Webshare, confirma que sea Residential rotativo y no Static/Proxy Server."
        )
    if isinstance(exc, NoTranscriptFound):
        return "Este video no tiene transcript disponible en los idiomas solicitados."
    if isinstance(exc, TranscriptsDisabled):
        return "Este video tiene los subtítulos deshabilitados."
    if isinstance(exc, AgeRestricted):
        return "Este video tiene restricción de edad y no se puede extraer el transcript automáticamente."
    if isinstance(exc, VideoUnavailable):
        return "Este video ya no está disponible en YouTube."
    if isinstance(exc, VideoUnplayable):
        return "YouTube marcó este video como no reproducible para la extracción automática."
    if isinstance(exc, InvalidVideoId):
        return "La URL de YouTube no contiene un video válido."
    if isinstance(exc, YouTubeRequestFailed):
        return "Falló la petición a YouTube durante la extracción del transcript."
    if isinstance(exc, CouldNotRetrieveTranscript):
        return "No se pudo recuperar el transcript de YouTube."
    message = str(exc).strip()
    return message or "Error desconocido al extraer el transcript de YouTube."


def extract_transcript(video_id: str, languages: list[str] = None) -> dict:
    """
    Extrae el transcript de un video de YouTube.
    
    Returns:
        dict con keys: titulo, contenido, identificador, type, status
    """
    if languages is None:
        languages = ["es", "en"]

    result = {
        "identificador": video_id,
        "type": "video",
        "titulo": "",
        "contenido": "",
        "status": "pending",
        "error": None,
    }

    try:
        result["titulo"] = get_video_title(video_id)

        ytt_api = _build_youtube_api()
        transcript = ytt_api.fetch(video_id, languages=languages)

        formatter = TextFormatter()
        text = formatter.format_transcript(transcript)
        result["contenido"] = text
        result["status"] = "success"

    except Exception as e:
        logger.warning("[P1] Transcript extraction failed for %s: %s", video_id, e)
        result["status"] = "error"
        result["error"] = _short_youtube_error(e)
        result["contenido"] = f"Error al extraer transcript: {result['error']}"

    return result
