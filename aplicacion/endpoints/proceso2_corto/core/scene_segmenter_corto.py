"""
Scene Segmenter Corto — Segmenta audio corto en escenas usando solo SRT.
Para videos cortos (≤ 2 min), sin markers de sección.
Las escenas resultantes alimentan el Proceso 3 (enriquecimiento para IA).
"""
import json


def segment_into_scenes_corto(
	srt_segments: list,
	scene_duration_target: float = 5.0,
) -> list:
	"""
	Segmenta un audio corto en escenas basándose solo en segmentos SRT.

	No usa markers de sección (intro/partes/cierre) porque el audio corto
	es un solo archivo sin divisiones.

	Cada escena contiene:
	- scene_num: número secuencial
	- start / end: timestamps en segundos
	- text: texto combinado del SRT
	- duration: duración en segundos

	Args:
		srt_segments: lista de {start, end, text} del SRT
		scene_duration_target: duración objetivo en segundos (default 5s para cortos)
	"""
	if not srt_segments:
		return []

	scenes = []
	current_scene_start = srt_segments[0]["start"]
	current_texts = []

	for seg in srt_segments:
		current_texts.append(seg["text"])
		elapsed = seg["end"] - current_scene_start

		if elapsed >= scene_duration_target:
			scenes.append({
				"scene_num": len(scenes) + 1,
				"section": "main",
				"start": round(current_scene_start, 3),
				"end": round(seg["end"], 3),
				"text": " ".join(current_texts).strip(),
				"duration": round(seg["end"] - current_scene_start, 2),
			})
			current_scene_start = seg["end"]
			current_texts = []

	# Última escena con texto restante
	if current_texts and srt_segments:
		last_end = srt_segments[-1]["end"]
		scenes.append({
			"scene_num": len(scenes) + 1,
			"section": "main",
			"start": round(current_scene_start, 3),
			"end": round(last_end, 3),
			"text": " ".join(current_texts).strip(),
			"duration": round(last_end - current_scene_start, 2),
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

	total_duration = sum(s["duration"] for s in scenes)
	avg_duration = total_duration / len(scenes) if scenes else 0

	return {
		"total_scenes": len(scenes),
		"total_duration": round(total_duration, 2),
		"avg_scene_duration": round(avg_duration, 2),
		"min_scene_duration": round(min(s["duration"] for s in scenes), 2),
		"max_scene_duration": round(max(s["duration"] for s in scenes), 2),
	}
