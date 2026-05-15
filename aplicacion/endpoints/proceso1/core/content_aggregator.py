"""
Content Aggregator — Estructura el JSON final con todas las fuentes.
Proceso 1, módulo core.
"""
import json


def aggregate_sources(project_id: str, sources: list[dict]) -> dict:
    """
    Agrega todas las fuentes extraídas en un JSON estructurado.
    """
    guion = {
        "id_guion": project_id,
        "total_items": len(sources),
        "contenido_fuentes": [],
    }

    for index, source in enumerate(sources):
        tipo = source.get("type", "desconocido")
        titulo = source.get("titulo", "Sin Título")
        texto = source.get("contenido", "")

        guion["contenido_fuentes"].append({
            "fuente_n": index + 1,
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
        })

    return guion


def format_for_prompt(aggregated: dict) -> str:
    """
    Convierte el JSON agregado a un string formateado para insertarlo en el prompt.
    """
    return json.dumps(aggregated, ensure_ascii=False, indent=2)


def format_optimized(aggregated: dict) -> str:
    """
    Versión compacta (una sola línea) para ahorrar tokens.
    """
    return json.dumps(aggregated, ensure_ascii=False, separators=(",", ":"))
