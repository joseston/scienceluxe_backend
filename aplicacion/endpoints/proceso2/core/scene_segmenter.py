"""
Scene Segmenter — Cruza markers de sección con SRT para crear escenas.
Proceso 3, lógica de segmentación heurística.
"""
import json


def segment_into_scenes(
    markers: dict,
    srt_segments: list,
    scene_duration_target: float = 18.0,
) -> list:
    """
    Cruza markers de sección con segmentos SRT para crear escenas.

    Cada escena contiene:
    - scene_num: número secuencial
    - section: nombre de la sección (intro, parte1, etc.)
    - start / end: timestamps en segundos
    - text: texto combinado del SRT
    - duration: duración en segundos

    Args:
        markers: dict con {label: {start, end, duration}} de cada sección
        srt_segments: lista de {start, end, text} del SRT
        scene_duration_target: duración objetivo de cada escena en segundos
    """
    scenes = []

    # Filtrar markers internos (los que empiezan con _)
    section_labels = [k for k in markers if not k.startswith("_")]

    for section_label in section_labels:
        section = markers[section_label]
        sec_start = section["start"]
        sec_end = section["end"]

        # Filtrar segmentos SRT que caen en esta sección
        section_segments = [
            s for s in srt_segments
            if s["start"] >= sec_start - 0.5 and s["start"] < sec_end + 0.5
        ]

        if not section_segments:
            continue

        # Subdividir en escenas por duración objetivo
        current_scene_start = section_segments[0]["start"]
        current_texts = []

        for seg in section_segments:
            current_texts.append(seg["text"])
            elapsed = seg["end"] - current_scene_start

            if elapsed >= scene_duration_target:
                scenes.append({
                    "scene_num": len(scenes) + 1,
                    "section": section_label,
                    "start": round(current_scene_start, 3),
                    "end": round(seg["end"], 3),
                    "text": " ".join(current_texts).strip(),
                    "duration": round(seg["end"] - current_scene_start, 2),
                })
                current_scene_start = seg["end"]
                current_texts = []

        # Última escena de la sección
        if current_texts and section_segments:
            scenes.append({
                "scene_num": len(scenes) + 1,
                "section": section_label,
                "start": round(current_scene_start, 3),
                "end": round(section_segments[-1]["end"], 3),
                "text": " ".join(current_texts).strip(),
                "duration": round(section_segments[-1]["end"] - current_scene_start, 2),
            })

    return scenes


def export_scenes_json(scenes: list, output_path: str) -> str:
    """Exporta escenas a JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, indent=2, ensure_ascii=False)
    return output_path


def get_scene_stats(scenes: list) -> dict:
    """Calcula estadísticas de las escenas."""
    if not scenes:
        return {"total_scenes": 0}

    sections = set(s["section"] for s in scenes)
    total_duration = sum(s["duration"] for s in scenes)
    avg_duration = total_duration / len(scenes) if scenes else 0

    return {
        "total_scenes": len(scenes),
        "total_sections": len(sections),
        "total_duration": round(total_duration, 2),
        "avg_scene_duration": round(avg_duration, 2),
        "sections": {
            sec: len([s for s in scenes if s["section"] == sec])
            for sec in sections
        },
    }
