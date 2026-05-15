"""
Article Extractor — Extrae contenido de artículos web.
Proceso 1, módulo core.
"""
import trafilatura


def extract_article(url: str) -> dict:
    """
    Extrae el contenido de un artículo web usando trafilatura.
    
    Returns:
        dict con keys: titulo, contenido, identificador, type, status
    """
    result = {
        "identificador": url,
        "type": "article",
        "titulo": "",
        "contenido": "",
        "status": "pending",
        "error": None,
    }

    try:
        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            result["status"] = "error"
            result["error"] = "No se pudo descargar la página"
            result["titulo"] = "Error de Descarga"
            return result

        metadata = trafilatura.extract(
            downloaded,
            output_format="json",
            include_comments=False,
            include_tables=False,
        )

        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
        )

        if metadata:
            import json
            meta_dict = json.loads(metadata)
            result["titulo"] = meta_dict.get("title", "Artículo Sin Título")
        else:
            result["titulo"] = "Artículo Sin Título"

        if content:
            result["contenido"] = content
            result["status"] = "success"
            
            if result["titulo"] == "Artículo Sin Título":
                lines = content.split("\n")
                if lines:
                    result["titulo"] = lines[0][:100]
        else:
            result["status"] = "error"
            result["error"] = "No se pudo extraer contenido"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["contenido"] = f"Error al extraer artículo: {str(e)}"

    return result
