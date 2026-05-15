from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path

from flask import current_app, jsonify, request

from aplicacion import db
from aplicacion.models.proceso1 import Proceso1SubprocessState
from aplicacion.models.proceso3 import Proceso3SubprocessState
from aplicacion.models.proceso4 import (
	Proceso4SceneMedia,
	Proceso4SubprocessState,
)

from .. import proceso4_bp
from ..prompt_templates import (
	build_text_to_video_prompt,
	build_text_to_image_prompt,
	build_text_to_image_final_prompt,
	build_text_to_animation_prompt,
	build_image_to_video_prompt,
	DEFAULT_ESTILO_CANAL,
)
from ..helpers import (
	get_or_create_job,
	get_or_create_subprocess_state,
	_save_state,
	_effective_clip_duration,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt Station
# ---------------------------------------------------------------------------

def _get_tema_principal(pid: int) -> str:
	"""Read tema_principal from P1 subprocess state subproceso2."""
	state = Proceso1SubprocessState.query.filter_by(
		job_id=pid,
		subprocess_key='subproceso2',
	).first()
	if not state:
		return 'Documental Científico'
	estimated = (state.output_payload or {}).get('estructura', {})
	return str(estimated.get('tema_principal', 'Documental Científico'))


def _get_estilo_canal(pid: int) -> str:
	"""Read estilo_canal from P4 config subprocess state."""
	config_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='config',
	).first()
	if not config_state:
		return DEFAULT_ESTILO_CANAL
	return str((config_state.output_payload or {}).get('estilo_canal', DEFAULT_ESTILO_CANAL))


def _get_imported_scenes(pid: int) -> list[dict]:
	"""Return the canonical scene list from the P4 import_timeline, enriched with any
	extra fields (e.g. physical_composition) from P3 batch states.

	The P4 import_timeline is the single source of truth for scene_num and section,
	because it was patched to have sequential 1..N scene_nums and may contain scenes
	that are missing from individual P3 batch states.
	"""
	# --- Always start from P4 import_timeline (authoritative scene_nums + sections) ---
	import_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='import_timeline',
	).first()
	if not import_state:
		return []
	tl = (import_state.output_payload or {}).get('timeline', {})
	tl_scenes: list[dict] = tl.get('scenes', [])
	if not tl_scenes:
		return []

	# --- Enrich with extra fields from P3 batch states (matched by start time) ---
	batch_states = Proceso3SubprocessState.query.filter(
		Proceso3SubprocessState.proceso1_job_id == pid,
		Proceso3SubprocessState.subprocess_key.like('batch_%'),
		Proceso3SubprocessState.status == 'completed',
	).all()

	if batch_states:
		batch_scenes: list[dict] = []
		for st in batch_states:
			sc = (st.output_payload or {}).get('scenes') or []
			if isinstance(sc, list):
				batch_scenes.extend(sc)

		# Build a lookup: start_time (rounded to 2dp) → scene dict
		EXTRA_FIELDS = ('physical_composition',)
		batch_by_start: dict[str, dict] = {}
		for s in batch_scenes:
			key = f"{float(s.get('start', 0.0)):.2f}"
			batch_by_start[key] = s

		enriched: list[dict] = []
		for s in tl_scenes:
			key = f"{float(s.get('start', 0.0)):.2f}"
			batch_s = batch_by_start.get(key)
			if batch_s:
				extras = {f: batch_s[f] for f in EXTRA_FIELDS if f in batch_s and f not in s}
				enriched.append({**s, **extras})
			else:
				enriched.append(s)
		return enriched

	return tl_scenes


def _brief_text(value: object, limit: int = 280) -> str:
	text = re.sub(r'\s+', ' ', str(value or '')).strip()
	if len(text) <= limit:
		return text
	return text[:limit].rstrip() + '...'


def _sanitize_json_control_chars(json_str: str) -> str:
	control_map = {'\n': '\\n', '\r': '\\r', '\t': '\\t', '\b': '\\b', '\f': '\\f'}
	result: list[str] = []
	in_string = False
	escaped = False
	for ch in json_str:
		if escaped:
			result.append(ch)
			escaped = False
		elif ch == '\\' and in_string:
			result.append(ch)
			escaped = True
		elif ch == '"':
			result.append(ch)
			in_string = not in_string
		elif in_string and ch in control_map:
			result.append(control_map[ch])
		else:
			result.append(ch)
	return ''.join(result)


def _parse_visual_brief_response(raw_text: str) -> list[dict]:
	match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text or '', re.IGNORECASE)
	if not match:
		match = re.search(r'```\s*([\s\S]*?)\s*```', raw_text or '')
	json_str = match.group(1) if match else (raw_text or '')
	if '[' in json_str and ']' in json_str:
		json_str = json_str[json_str.find('['):json_str.rfind(']') + 1]
	json_str = _sanitize_json_control_chars(json_str)
	data = json.loads(json_str)
	if isinstance(data, dict):
		data = data.get('scenes') or data.get('visual_briefs') or []
	return data if isinstance(data, list) else []


def _fallback_visual_brief(scene: dict, tema_principal: str) -> dict:
	concept = _brief_text(scene.get('visual_description') or '')
	physical = _brief_text(scene.get('physical_composition') or '')
	narration = _brief_text(scene.get('text') or '', 180)
	primary_source = concept or physical or narration or tema_principal
	materials = physical or concept or tema_principal
	relationship_scene = _is_relationship_visual_scene(scene)
	visual_purpose = (
		"make the scientific relationship, comparison, scale, process, or cause-effect idea readable without text"
		if relationship_scene
		else "make the scene's main scientific subject immediately recognizable"
	)
	layout_constraints = (
		"keep all compared or related subjects clearly visible as readable references; do not hide a scale reference as a tiny corner detail"
		if relationship_scene
		else "preserve enough context, scale, and environment for the main subject to be understood"
	)
	required_visual_elements = (
		_brief_text(f"{materials}; any concrete visual reference needed to explain the narration", 260)
		if relationship_scene
		else materials
	)
	negative_guardrails = (
		"no missing relationship, no single-subject hero shot, no hidden scale reference, no text, no labels, no UI elements, no abstract materials only"
		if relationship_scene
		else "no missing main subject, no abstract materials only, no generic texture only, no empty darkness only"
	)
	return {
		'visual_purpose': visual_purpose,
		'primary_visible_subject': primary_source,
		'visual_hierarchy': (
			f"Read the main subject first, then the action/context, then the physical materials: {materials}"
		),
		'required_visual_elements': required_visual_elements,
		'layout_constraints': layout_constraints,
		'palette_lighting': (
			"Use the channel style, documentary cinematic lighting, visible physical textures, and scene-specific colors."
		),
		'negative_guardrails': negative_guardrails,
	}


def _is_relationship_visual_scene(scene: dict) -> bool:
	"""Detect scenes whose main subject is a visual relationship, not one hero object."""
	visual_type = str(scene.get('visual_type') or '').lower()
	concept = str(scene.get('visual_description') or '').lower()
	narration = str(scene.get('text') or '').lower()
	physical = str(scene.get('physical_composition') or '').lower()
	blob = f"{visual_type} {concept} {narration} {physical}"
	keywords = (
		'graphic',
		'comparison',
		'compare',
		'compares',
		'versus',
		' vs ',
		'scale',
		'stronger',
		'weaker',
		'larger',
		'smaller',
		'times the',
		'times stronger',
		'than earth',
		'before and after',
		'before/after',
		'cause and effect',
		'cause-effect',
		'process',
		'diagram',
	)
	return any(keyword in blob for keyword in keywords)


def _title_physical_anchor(scene: dict, tema_principal: str) -> str:
	title = str(tema_principal or '').lower()
	physical = str(scene.get('physical_composition') or '')
	for raw_part in physical.split(','):
		part = re.sub(r'\s+', ' ', raw_part).strip()
		if not part:
			continue
		if len(part) < 3:
			continue
		if part.lower() in title:
			return part
	return ''


def _prepend_if_missing(text: str, prefix: str, required: str) -> str:
	text = _brief_text(text)
	if required.lower() in text.lower():
		return text
	return _brief_text(f"{prefix}; {text}" if text else prefix)


def _prepend_negative_guardrails(text: str, guardrails: list[str]) -> str:
	existing = _brief_text(text)
	parts: list[str] = []
	for guardrail in guardrails:
		if guardrail.lower() not in existing.lower():
			parts.append(guardrail)
	if existing:
		parts.append(existing)
	return _brief_text(', '.join(parts))


def _reinforce_title_anchor(scene: dict, tema_principal: str, brief: dict) -> dict:
	anchor = _title_physical_anchor(scene, tema_principal)
	if not anchor:
		return brief

	reinforced = dict(brief)
	relationship_scene = _is_relationship_visual_scene(scene)
	anchor_lower = anchor.lower()
	if relationship_scene:
		reinforced['primary_visible_subject'] = _prepend_if_missing(
			reinforced.get('primary_visible_subject', ''),
			f"{anchor} visible as one readable subject in the scientific relationship",
			anchor,
		)
		reinforced['visual_hierarchy'] = _prepend_if_missing(
			reinforced.get('visual_hierarchy', ''),
			f"the visual relationship reads first, {anchor} remains clearly recognizable as one comparison/process subject, supporting details third",
			anchor,
		)
		reinforced['layout_constraints'] = _prepend_if_missing(
			reinforced.get('layout_constraints', ''),
			"do not turn the scene into a single-subject hero shot; all required relationship subjects must remain readable",
			'relationship',
		)
		reinforced['required_visual_elements'] = _prepend_if_missing(
			reinforced.get('required_visual_elements', ''),
			f"{anchor} and every required scale/process/cause-effect reference",
			anchor,
		)
		reinforced['negative_guardrails'] = _prepend_negative_guardrails(
			reinforced.get('negative_guardrails', ''),
			[
				'no missing relationship',
				'no single-subject hero shot',
				'no hidden scale reference',
				f'no missing {anchor}',
				'no text',
				'no labels',
				'no UI elements',
			],
		)
		return reinforced

	if anchor_lower == 'jupiter':
		reinforced['primary_visible_subject'] = _prepend_if_missing(
			reinforced.get('primary_visible_subject', ''),
			"Jupiter's recognizable curved banded atmosphere as the larger visible context",
			'Jupiter',
		)
		reinforced['visual_hierarchy'] = _prepend_if_missing(
			reinforced.get('visual_hierarchy', ''),
			"Jupiter reads first through curved/banded planetary context, the action subject second, ammonia clouds/material depth third",
			'Jupiter',
		)
		reinforced['palette_lighting'] = _prepend_if_missing(
			reinforced.get('palette_lighting', ''),
			"brown, cream, ochre and orange Jovian bands, white ammonia clouds, deep blue-black atmospheric shadows",
			'Jovian',
		)
		reinforced['negative_guardrails'] = _prepend_negative_guardrails(
			reinforced.get('negative_guardrails', ''),
			[
				'no missing Jupiter',
				'no ammonia fog only',
				'no empty black background',
				'no close-up without planetary context',
				'no planetless atmosphere',
			],
		)
		return reinforced

	reinforced['primary_visible_subject'] = _prepend_if_missing(
		reinforced.get('primary_visible_subject', ''),
		f"{anchor} visually recognizable as the larger visible context",
		anchor,
	)
	reinforced['visual_hierarchy'] = _prepend_if_missing(
		reinforced.get('visual_hierarchy', ''),
		f"{anchor} reads first as the larger visible context, the action subject second, materials/depth third",
		anchor,
	)
	reinforced['negative_guardrails'] = _prepend_negative_guardrails(
		reinforced.get('negative_guardrails', ''),
		[
			f'no missing {anchor}',
			'no abstract materials only',
			'no generic texture only',
			'no close-up without context',
		],
	)
	return reinforced


def _normalize_visual_brief(item: dict, scene: dict, tema_principal: str) -> dict:
	fallback = _fallback_visual_brief(scene, tema_principal)
	if not isinstance(item, dict):
		return _reinforce_title_anchor(scene, tema_principal, fallback)

	brief = {
		'visual_purpose': _brief_text(
			item.get('visual_purpose') or fallback['visual_purpose']
		),
		'primary_visible_subject': _brief_text(
			item.get('primary_visible_subject') or fallback['primary_visible_subject']
		),
		'visual_hierarchy': _brief_text(
			item.get('visual_hierarchy') or fallback['visual_hierarchy']
		),
		'required_visual_elements': _brief_text(
			item.get('required_visual_elements') or fallback['required_visual_elements']
		),
		'layout_constraints': _brief_text(
			item.get('layout_constraints') or fallback['layout_constraints']
		),
		'palette_lighting': _brief_text(
			item.get('palette_lighting') or fallback['palette_lighting']
		),
		'negative_guardrails': _brief_text(
			item.get('negative_guardrails') or fallback['negative_guardrails']
		),
	}
	return _reinforce_title_anchor(scene, tema_principal, brief)


def _build_visual_brief_prompt(
	tema_principal: str,
	section: str,
	section_scenes: list[dict],
) -> str:
	scenes_payload = []
	for scene in section_scenes:
		scenes_payload.append({
			'scene_num': scene.get('scene_num', 0),
			'text': _brief_text(scene.get('text'), 500),
			'visual_description': _brief_text(scene.get('visual_description'), 350),
			'physical_composition': _brief_text(scene.get('physical_composition'), 300),
			'visual_type': _brief_text(scene.get('visual_type'), 80),
		})

	scenes_json = json.dumps(scenes_payload, ensure_ascii=False, indent=2)
	return f"""You are a visual director for scientific documentary AI image prompts.

Your task is NOT to write final image prompts. Create one compact visual brief per scene so a later template can generate better text-to-image prompts.

Video title: {tema_principal}
Section: {section}

For each scene, infer the visual purpose and visible hierarchy that prevent the image model from drawing only isolated materials or a beautiful but wrong single-subject image. Keep every field short, concrete, and image-oriented.

CRITICAL PRIORITY RULES:
- Your job is to create a visual brief, not a rigid art direction blueprint. Do not over-specify exact positions, percentages, camera angles, or object counts unless essential to the scene.
- Distinguish SUBJECT scenes from RELATIONSHIP scenes. If the scene is about comparison, scale, before/after, cause/effect, process, frequency, intensity, or a Graphic visual type, the main subject is the relationship itself.
- For relationship scenes, visual_purpose must state the relationship clearly, and visual_hierarchy must make the relationship read first. Do not reduce the scene to a hero shot of the biggest object.
- For relationship scenes, required_visual_elements must list every concrete visible reference needed to understand the narration, even if the reference is not a material. Example: if the narration says "power a small city", include a readable small city power-grid silhouette, city lights, or urban energy reference.
- For relationship scenes, layout_constraints must keep every required comparison/process subject readable, especially smaller scale references. Avoid hiding the smaller reference in a corner.
- For Graphic visual types, prefer "cinematic no-text scientific comparison/explainer image" over flat infographic UI. Do not require labels, numbers, arrows, charts, or interface elements.
- If a named entity appears in both the video title and physical_composition, treat it as a mandatory visible anchor unless the scene explicitly says it must be invisible.
- If physical_composition contains a larger named environment/body/location (planet, moon, ocean, volcano, human body, cell, spacecraft, laboratory, city, star, black hole), do not let smaller materials (fog, gas, crystals, dust, darkness, smoke, particles, liquid) become the whole image.
- visual_description defines the action, but it must not erase the larger visible context that makes the scene recognizable.
- For inside/within/falling-through atmosphere scenes, preserve the larger environment through horizon curvature, scale cues, cutaway framing, surface/cloud bands, structure, or contextual wide framing.
- Darkness, fog, gas, haze, crystals, particles, or smoke must be depth/material, not the entire composition, unless no larger subject exists.
- If the title is about a specific place/object (for example Jupiter) and the scene happens inside/near it, the place/object must remain visually recognizable through contextual cues.

Return ONLY valid JSON, no markdown, exactly an array with one object per scene:
[
  {{
    "scene_num": 1,
    "visual_purpose": "what the image must communicate at first glance",
    "primary_visible_subject": "what must be immediately recognizable on screen",
    "visual_hierarchy": "what reads first, second, third",
    "required_visual_elements": "concrete visible elements needed to make the idea understandable",
    "layout_constraints": "flexible composition constraints that protect the purpose without over-directing exact positions",
    "palette_lighting": "scene-specific colors and lighting",
    "negative_guardrails": "comma-separated no... failures to avoid"
  }}
]

Rules:
- Do not write POSITIVE PROMPT or NEGATIVE PROMPT.
- The complete brief per scene should be compact, roughly 70-150 tokens.
- visual_purpose must define the image's mission, such as "recognize the main subject", "no-text scale comparison", "show a process", "show cause and effect", or "show before/after".
- required_visual_elements must include the necessary visual anchors from physical_composition plus any concrete explanatory reference implied by narration. Keep it visual and object-based, not abstract.
- If a planet, person, machine, organism, location, or object is important, make it visually recognizable, not merely implied.
- primary_visible_subject must include the larger mandatory anchor first when one exists, then the action subject.
- visual_hierarchy must explicitly say what reads first, second, and third.
- layout_constraints must be flexible. It may say "both comparison subjects must be readable" but should not say exact left/right percentages unless essential.
- palette_lighting must mention the larger anchor's recognizable colors/lighting when available.
- negative_guardrails must include concrete visual failures, such as missing named anchor, missing comparison, single-subject hero shot, hidden scale reference, abstract fog only, generic texture only, close-up without context, planetless/bodyless/placeless atmosphere, empty darkness only, or text/UI when relevant.
- Use English for all field values.

Examples of correct behavior:
If title is about Jupiter and physical_composition includes Jupiter plus ammonia crystals, do not answer "probe in ammonia haze" as the primary subject. Answer with Jupiter's recognizable curved/banded atmosphere first, the probe second, and ammonia cloud deck third. Include guardrails like "no missing Jupiter, no ammonia fog only, no empty black background, no close-up without planetary context".
If visual_type is Graphic and the concept compares Jovian flashes to Earth lightning, do not answer "Jupiter storm clouds filling most of the frame with tiny Earth in the corner". The visual_purpose is a no-text scale comparison; both Jupiter storm clouds and Earth storm clouds must be readable. Include guardrails like "no single Jupiter-only hero shot, no hidden Earth, no missing comparison layout, no text, no labels, no UI elements".

Scenes:
{scenes_json}"""


def _call_gemini_visual_briefs(prompt: str, pid: int, section: str) -> str:
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
	if not api_key:
		from config import GEMINI_API_KEY, GEMINI_MODEL
		api_key = GEMINI_API_KEY
		model_name = GEMINI_MODEL

	if not api_key:
		raise RuntimeError('GEMINI_API_KEY not configured')

	try:
		import google.generativeai as genai
	except ImportError as exc:
		raise RuntimeError('Missing dependency: pip install google-generativeai') from exc

	prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]
	logger.info(
		"[P4 prompt_station] visual brief Gemini start job=%s section=%s model=%s promptChars=%s promptHash=%s",
		pid,
		section,
		model_name,
		len(prompt),
		prompt_hash,
	)
	started = time.perf_counter()
	genai.configure(api_key=api_key)
	model = genai.GenerativeModel(model_name)
	resp = model.generate_content(prompt)
	raw = resp.text or ''
	logger.info(
		"[P4 prompt_station] visual brief Gemini success job=%s section=%s latencyMs=%s rawChars=%s",
		pid,
		section,
		int((time.perf_counter() - started) * 1000),
		len(raw),
	)
	return raw


def _generate_visual_briefs_for_section(
	pid: int,
	section: str,
	section_scenes: list[dict],
	tema_principal: str,
) -> dict[int, dict]:
	briefs: dict[int, dict] = {
		int(scene.get('scene_num', 0)): _reinforce_title_anchor(
			scene,
			tema_principal,
			_fallback_visual_brief(scene, tema_principal),
		)
		for scene in section_scenes
	}
	if not section_scenes:
		return briefs

	try:
		prompt = _build_visual_brief_prompt(tema_principal, section, section_scenes)
		raw = _call_gemini_visual_briefs(prompt, pid, section)
		parsed = _parse_visual_brief_response(raw)
		scenes_by_num = {
			int(scene.get('scene_num', 0)): scene
			for scene in section_scenes
		}
		for item in parsed:
			try:
				scene_num = int(item.get('scene_num', 0))
			except Exception:
				continue
			scene = scenes_by_num.get(scene_num)
			if not scene:
				continue
			briefs[scene_num] = _normalize_visual_brief(item, scene, tema_principal)
	except Exception as exc:
		logger.warning(
			"[P4 prompt_station] visual brief Gemini failed job=%s section=%s; using local fallback: %s",
			pid,
			section,
			exc,
		)

	return briefs


def _normalize_prompt_station_variants(section_payload: object) -> dict[str, list[dict]]:
	if isinstance(section_payload, list):
		return {
			'metadata': [item for item in section_payload if isinstance(item, dict)],
			'final': [],
		}
	if isinstance(section_payload, dict):
		metadata_items = section_payload.get('metadata')
		final_items = section_payload.get('final')
		return {
			'metadata': [item for item in (metadata_items or []) if isinstance(item, dict)],
			'final': [item for item in (final_items or []) if isinstance(item, dict)],
		}
	return {'metadata': [], 'final': []}


def _empty_prompt_station_scene_entry(scene_num: int, section: str) -> dict:
	return {
		'scene_num': scene_num,
		'section': section,
		'duration': 0.0,
		'text': '',
		'visual_type': '',
		'visual_description': '',
		'physical_composition': '',
		'visual_brief': None,
		'text_to_video_prompt': '',
		'text_to_image_prompt_metadata': '',
		'text_to_image_prompt_final': '',
		'text_to_image_positive_prompt_final': '',
		'text_to_image_negative_prompt_final': '',
		'text_to_image_prompt': '',
		'image_to_video_prompt': '',
		'text_to_animation_prompt': '',
	}


def _merge_prompt_station_section_prompts(section: str, section_scenes: list[dict], section_payload: object) -> list[dict]:
	variants = _normalize_prompt_station_variants(section_payload)
	merged: dict[int, dict] = {}

	for scene in section_scenes:
		try:
			scene_num = int(scene.get('scene_num', 0))
		except Exception:
			continue
		entry = _empty_prompt_station_scene_entry(scene_num, section)
		entry.update({
			'duration': float(scene.get('duration', 0) or 0),
			'text': str(scene.get('text', '')),
			'visual_type': str(scene.get('visual_type', '')),
			'visual_description': str(scene.get('visual_description', '')),
			'physical_composition': str(scene.get('physical_composition', '')),
		})
		merged[scene_num] = entry

	for item in variants['metadata']:
		try:
			scene_num = int(item.get('scene_num', 0))
		except Exception:
			continue
		entry = merged.setdefault(scene_num, _empty_prompt_station_scene_entry(scene_num, section))
		entry.update({
			'section': str(item.get('section', entry['section']) or entry['section']),
			'duration': float(item.get('duration', entry['duration']) or 0),
			'text': str(item.get('text', entry['text']) or entry['text']),
			'visual_type': str(item.get('visual_type', entry['visual_type']) or entry['visual_type']),
			'visual_description': str(item.get('visual_description', entry['visual_description']) or entry['visual_description']),
			'physical_composition': str(item.get('physical_composition', entry['physical_composition']) or entry['physical_composition']),
			'visual_brief': item.get('visual_brief') or entry.get('visual_brief'),
			'text_to_video_prompt': str(item.get('text_to_video_prompt', entry['text_to_video_prompt']) or entry['text_to_video_prompt']),
			'text_to_image_prompt_metadata': str(
				item.get('text_to_image_prompt_metadata')
				or item.get('text_to_image_prompt')
				or entry['text_to_image_prompt_metadata']
			),
			'image_to_video_prompt': str(item.get('image_to_video_prompt', entry['image_to_video_prompt']) or entry['image_to_video_prompt']),
			'text_to_animation_prompt': str(item.get('text_to_animation_prompt', entry['text_to_animation_prompt']) or entry['text_to_animation_prompt']),
		})
		entry['text_to_image_prompt'] = entry['text_to_image_prompt_metadata']

	for item in variants['final']:
		try:
			scene_num = int(item.get('scene_num', 0))
		except Exception:
			continue
		entry = merged.setdefault(scene_num, _empty_prompt_station_scene_entry(scene_num, section))
		entry.update({
			'section': str(item.get('section', entry['section']) or entry['section']),
			'duration': float(item.get('duration', entry['duration']) or 0),
			'text': str(item.get('text', entry['text']) or entry['text']),
			'visual_type': str(item.get('visual_type', entry['visual_type']) or entry['visual_type']),
			'visual_description': str(item.get('visual_description', entry['visual_description']) or entry['visual_description']),
			'physical_composition': str(item.get('physical_composition', entry['physical_composition']) or entry['physical_composition']),
			'visual_brief': item.get('visual_brief') or entry.get('visual_brief'),
			'text_to_image_prompt_final': str(
				item.get('text_to_image_prompt_final', entry['text_to_image_prompt_final']) or entry['text_to_image_prompt_final']
			),
			'text_to_image_positive_prompt_final': str(
				item.get('text_to_image_positive_prompt_final', entry['text_to_image_positive_prompt_final']) or entry['text_to_image_positive_prompt_final']
			),
			'text_to_image_negative_prompt_final': str(
				item.get('text_to_image_negative_prompt_final', entry['text_to_image_negative_prompt_final']) or entry['text_to_image_negative_prompt_final']
			),
		})

	return [merged[scene_num] for scene_num in sorted(merged.keys())]


def _build_section_summary_source(section_scenes: list[dict]) -> str:
	ordered = sorted(section_scenes, key=lambda item: int(item.get('scene_num', 0) or 0))
	lines: list[str] = []
	for scene in ordered:
		text = str(scene.get('text', '') or '').strip()
		if not text:
			continue
		lines.append(f"S{int(scene.get('scene_num', 0) or 0)}: {text}")
	return "\n".join(lines)


def _section_summary_hash(section_text: str) -> str:
	return hashlib.sha256(section_text.encode('utf-8')).hexdigest()[:16]


def _build_section_summary_prompt(section: str, scene_count: int, section_text: str) -> str:
	return f"""Resume en español esta sección completa del documental en 4-6 frases claras.
Explica qué se está diciendo, cuál es la idea central, qué progresión narrativa tiene y qué puntos científicos importantes aparecen.
No inventes datos. No resumas escena por escena en lista; produce un párrafo fluido.

Sección: {section}
Cantidad de escenas: {scene_count}

Texto narrativo completo de la sección:
{section_text}"""


def _call_gemini_section_summary(prompt: str, pid: int, section: str) -> str:
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
	if not api_key:
		from config import GEMINI_API_KEY, GEMINI_MODEL
		api_key = GEMINI_API_KEY
		model_name = GEMINI_MODEL

	if not api_key:
		raise RuntimeError('GEMINI_API_KEY not configured')

	try:
		import google.generativeai as genai
	except ImportError as exc:
		raise RuntimeError('Missing dependency: pip install google-generativeai') from exc

	prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]
	logger.info(
		"[P4 section_summary] Gemini start job=%s section=%s model=%s promptChars=%s promptHash=%s",
		pid,
		section,
		model_name,
		len(prompt),
		prompt_hash,
	)
	started = time.perf_counter()
	genai.configure(api_key=api_key)
	model = genai.GenerativeModel(model_name)
	resp = model.generate_content(prompt)
	raw = resp.text or ''
	logger.info(
		"[P4 section_summary] Gemini success job=%s section=%s latencyMs=%s rawChars=%s",
		pid,
		section,
		int((time.perf_counter() - started) * 1000),
		len(raw),
	)
	return raw


def _get_cached_or_generate_section_summary(
	pid: int,
	section: str,
	section_scenes: list[dict],
	force: bool = False,
) -> tuple[str, bool]:
	section_text = _build_section_summary_source(section_scenes)
	if not section_text.strip():
		raise ValueError(f"La sección '{section}' no tiene texto narrativo para resumir.")

	text_hash = _section_summary_hash(section_text)
	summary_state = get_or_create_subprocess_state(pid, 'section_summaries')
	existing_output = dict(summary_state.output_payload or {})
	existing_payload = existing_output.get(section)

	if not force and isinstance(existing_payload, dict) and existing_payload.get('textHash') == text_hash:
		summary = str(existing_payload.get('summary', '') or '').strip()
		if summary:
			return summary, True

	prompt = _build_section_summary_prompt(section, len(section_scenes), section_text)
	raw_summary = _call_gemini_section_summary(prompt, pid, section)
	summary = re.sub(r'\s+', ' ', raw_summary.strip())
	if not summary:
		raise RuntimeError('Gemini no devolvió un resumen válido.')

	existing_output[section] = {
		'section': section,
		'sceneCount': len(section_scenes),
		'textHash': text_hash,
		'summary': summary,
		'generatedAt': time.time(),
	}
	_save_state(summary_state, {'status': 'completed', 'output': existing_output})
	return summary, False


def _scene_visual_guide_hash(scene: dict, section_text: str, section_summary: str) -> str:
	payload = {
		'scene_num': scene.get('scene_num', 0),
		'section': scene.get('section', ''),
		'text': scene.get('text', ''),
		'visual_type': scene.get('visual_type', ''),
		'visual_description': scene.get('visual_description', ''),
		'physical_composition': scene.get('physical_composition', ''),
		'section_text': section_text,
		'section_summary': section_summary,
	}
	return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def _build_scene_visual_guide_prompt(
	section: str,
	section_summary: str,
	section_text: str,
	scene: dict,
) -> str:
	return f"""Eres director visual de un documental científico.
Necesito una guía en español para evitar que una IA generadora de imagen/video cree algo incoherente.

Describe SOLO esta escena, pero conectándola con el resumen y la progresión de toda la sección.
Explica qué debe verse visualmente, qué elementos deben estar presentes, cómo se relaciona con la sección, y qué errores visuales evitar.
No escribas un prompt cinematográfico largo. No inventes datos. No propongas texto en pantalla, labels, UI, flechas ni gráficos salvo que la escena realmente lo pida.
Responde en 4 bloques cortos con estos títulos exactos:
Qué debe verse:
Relación con la sección:
Elementos obligatorios:
Evitar:

Sección: {section}
Resumen de la sección:
{section_summary}

Texto completo de la sección:
{section_text}

Escena objetivo:
S{int(scene.get('scene_num', 0) or 0)}
Narración: {str(scene.get('text', '') or '').strip()}
Tipo visual: {str(scene.get('visual_type', '') or '').strip()}
Visual base actual: {str(scene.get('visual_description', '') or '').strip()}
Composición física actual: {str(scene.get('physical_composition', '') or '').strip()}"""


def _call_gemini_scene_visual_guide(prompt: str, pid: int, section: str, scene_num: int) -> str:
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	model_name = current_app.config.get('GEMINI_MODEL', 'gemini-3-flash-preview')
	if not api_key:
		from config import GEMINI_API_KEY, GEMINI_MODEL
		api_key = GEMINI_API_KEY
		model_name = GEMINI_MODEL

	if not api_key:
		raise RuntimeError('GEMINI_API_KEY not configured')

	try:
		import google.generativeai as genai
	except ImportError as exc:
		raise RuntimeError('Missing dependency: pip install google-generativeai') from exc

	prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]
	logger.info(
		"[P4 scene_visual_guide] Gemini start job=%s section=%s scene=%s model=%s promptChars=%s promptHash=%s",
		pid,
		section,
		scene_num,
		model_name,
		len(prompt),
		prompt_hash,
	)
	started = time.perf_counter()
	genai.configure(api_key=api_key)
	model = genai.GenerativeModel(model_name)
	resp = model.generate_content(prompt)
	raw = resp.text or ''
	logger.info(
		"[P4 scene_visual_guide] Gemini success job=%s section=%s scene=%s latencyMs=%s rawChars=%s",
		pid,
		section,
		scene_num,
		int((time.perf_counter() - started) * 1000),
		len(raw),
	)
	return raw


@proceso4_bp.route('/jobs/<int:pid>/prompt-station', methods=['GET'])
def get_prompt_station(pid: int):
	"""Return all prompt-station data: config + generated prompts by section."""
	get_or_create_job(pid)

	# Config (estilo_canal)
	estilo_canal = _get_estilo_canal(pid)

	# Generated prompts (supports legacy list payloads and new variant payloads)
	ps_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='prompt_station',
	).first()
	generated = (ps_state.output_payload or {}) if ps_state else {}
	summary_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='section_summaries',
	).first()
	section_summaries = (summary_state.output_payload or {}) if summary_state else {}
	visual_guide_state = Proceso4SubprocessState.query.filter_by(
		proceso1_job_id=pid,
		subprocess_key='scene_visual_guides',
	).first()
	scene_visual_guides = (visual_guide_state.output_payload or {}) if visual_guide_state else {}

	# Build section summary from imported timeline
	scenes = _get_imported_scenes(pid)

	# Compute per-scene media coverage status for prompt-station badges
	all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
		Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
	).all()
	media_by_scene: dict[int, list] = {}
	for m in all_media:
		media_by_scene.setdefault(m.scene_num, []).append(m)

	def _scene_media_status(scene_num: int, scene_dur: float) -> str:
		clips = media_by_scene.get(scene_num, [])
		if not clips:
			return 'none'
		covered = 0.0
		for c in clips:
			covered += _effective_clip_duration(c)
		if covered >= scene_dur - 0.1:
			return 'complete'
		return 'partial'

	# Map scene_num -> duration from the imported timeline scenes
	scene_dur_map: dict[int, float] = {}
	for s in scenes:
		scene_dur_map[s.get('scene_num', 0)] = float(s.get('duration', 0))

	# Build ordered section list dynamically from the actual imported scenes
	# so that any number of parts (parte1..parteN) is supported.
	def _section_sort_key(sec: str) -> tuple:
		if sec == 'intro':
			return (0, 0)
		if sec == 'cierre':
			return (2, 0)
		# parteN → (1, N) so they sort numerically
		num_str = sec.replace('parte', '')
		try:
			return (1, int(num_str))
		except ValueError:
			return (1, 999)

	present_sections = sorted(
		{s.get('section', '') for s in scenes if s.get('section')},
		key=_section_sort_key,
	)
	# Also include any sections that already have generated prompts (even if no scenes)
	for sec in list(generated.keys()):
		if sec not in present_sections:
			present_sections.append(sec)
	present_sections = sorted(present_sections, key=_section_sort_key)

	section_summary_rows: list[dict] = []
	for section in present_sections:
		section_scenes = [s for s in scenes if s.get('section') == section]
		section_text = _build_section_summary_source(section_scenes)
		section_text_hash = _section_summary_hash(section_text) if section_text else ''
		summary_payload = section_summaries.get(section)
		cached_section_summary = ''
		if isinstance(summary_payload, dict) and summary_payload.get('textHash') == section_text_hash:
			cached_section_summary = str(summary_payload.get('summary', '') or '')
		section_variants = _normalize_prompt_station_variants(generated.get(section))
		has_any_variant_prompts = bool(section_variants['metadata'] or section_variants['final'])
		merged_prompts = (
			_merge_prompt_station_section_prompts(section, section_scenes, generated.get(section))
			if has_any_variant_prompts
			else []
		)
		enriched_prompts = []
		for p in merged_prompts:
			sn = p.get('scene_num', 0)
			sdur = scene_dur_map.get(sn, p.get('duration', 0) or 0)
			visual_guide_payload = scene_visual_guides.get(f'{section}:{sn}')
			visual_guide = ''
			if (
				cached_section_summary
				and isinstance(visual_guide_payload, dict)
				and visual_guide_payload.get('contextHash') == _scene_visual_guide_hash(p, section_text, cached_section_summary)
			):
				visual_guide = str(visual_guide_payload.get('guide', '') or '')
			enriched_prompts.append({
				**p,
				'mediaStatus': _scene_media_status(sn, sdur),
				'visualGuide': visual_guide,
				'visualGuideCached': bool(visual_guide),
			})
		metadata_generated = len(section_variants['metadata']) > 0 and len(section_variants['metadata']) >= len(section_scenes)
		final_generated = len(section_variants['final']) > 0 and len(section_variants['final']) >= len(section_scenes)

		# status "completed" ONLY when every scene in the section has
		# full media coverage (mediaStatus == 'complete').
		all_scenes_have_media = (
			len(section_scenes) > 0
			and all(
				_scene_media_status(
					s.get('scene_num', 0),
					float(s.get('duration', 0)),
				) == 'complete'
				for s in section_scenes
			)
		)
		section_summary_rows.append({
			'section': section,
			'sceneCount': len(section_scenes),
			'status': 'completed' if all_scenes_have_media else 'pending',
			'promptsGenerated': metadata_generated,
			'metadataPromptsGenerated': metadata_generated,
			'finalPromptsGenerated': final_generated,
			'sectionSummary': cached_section_summary,
			'sectionSummaryCached': bool(cached_section_summary),
			'prompts': enriched_prompts,
		})

	return jsonify({
		'estilo_canal': estilo_canal,
		'sections': section_summary_rows,
	})


@proceso4_bp.route('/jobs/<int:pid>/prompt-station/sections/<section>/summary', methods=['POST'])
def summarize_prompt_station_section(pid: int, section: str):
	"""Generate or return a cached Spanish summary for a full prompt-station section."""
	get_or_create_job(pid)
	section = (section or '').strip()
	body = request.get_json(silent=True) or {}
	force = bool(body.get('force'))

	if not section:
		return jsonify({'error': "El campo 'section' es requerido."}), 400

	scenes = _get_imported_scenes(pid)
	section_scenes = [s for s in scenes if s.get('section') == section]
	if not section_scenes:
		return jsonify({'error': f"No hay escenas para la sección '{section}'."}), 404

	section_text = _build_section_summary_source(section_scenes)
	if not section_text.strip():
		return jsonify({'error': f"La sección '{section}' no tiene texto narrativo para resumir."}), 400

	try:
		summary, cached = _get_cached_or_generate_section_summary(pid, section, section_scenes, force=force)
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400
	except RuntimeError as exc:
		return jsonify({'error': str(exc)}), 500
	except Exception as exc:
		logger.exception("[P4 section_summary] Gemini failed job=%s section=%s", pid, section)
		return jsonify({'error': f'No se pudo generar el resumen de sección: {exc}'}), 502

	return jsonify({
		'section': section,
		'sceneCount': len(section_scenes),
		'summary': summary,
		'cached': cached,
	})


@proceso4_bp.route('/jobs/<int:pid>/prompt-station/sections/<section>/scenes/<int:scene_num>/visual-guide', methods=['POST'])
def describe_prompt_station_scene_visual(pid: int, section: str, scene_num: int):
	"""Generate or return a cached visual guide for one scene in its section context."""
	get_or_create_job(pid)
	section = (section or '').strip()
	body = request.get_json(silent=True) or {}
	force = bool(body.get('force'))

	if not section:
		return jsonify({'error': "El campo 'section' es requerido."}), 400

	scenes = _get_imported_scenes(pid)
	section_scenes = [s for s in scenes if s.get('section') == section]
	if not section_scenes:
		return jsonify({'error': f"No hay escenas para la sección '{section}'."}), 404

	scene = next((s for s in section_scenes if int(s.get('scene_num', 0) or 0) == scene_num), None)
	if not scene:
		return jsonify({'error': f"La escena {scene_num} no existe en la sección '{section}'."}), 404

	if not str(scene.get('text', '') or '').strip():
		return jsonify({'error': f"La escena {scene_num} no tiene texto narrativo para analizar."}), 400

	section_text = _build_section_summary_source(section_scenes)
	if not section_text.strip():
		return jsonify({'error': f"La sección '{section}' no tiene texto narrativo para analizar."}), 400

	try:
		section_summary, summary_cached = _get_cached_or_generate_section_summary(pid, section, section_scenes, force=False)
	except ValueError as exc:
		return jsonify({'error': str(exc)}), 400
	except RuntimeError as exc:
		return jsonify({'error': str(exc)}), 500
	except Exception as exc:
		logger.exception("[P4 scene_visual_guide] Section summary failed job=%s section=%s scene=%s", pid, section, scene_num)
		return jsonify({'error': f'No se pudo preparar el resumen de sección: {exc}'}), 502

	context_hash = _scene_visual_guide_hash(scene, section_text, section_summary)
	guide_state = get_or_create_subprocess_state(pid, 'scene_visual_guides')
	existing_output = dict(guide_state.output_payload or {})
	cache_key = f'{section}:{scene_num}'
	existing_payload = existing_output.get(cache_key)

	if not force and isinstance(existing_payload, dict) and existing_payload.get('contextHash') == context_hash:
		guide = str(existing_payload.get('guide', '') or '').strip()
		if guide:
			return jsonify({
				'section': section,
				'sceneNum': scene_num,
				'guide': guide,
				'sectionSummary': section_summary,
				'sectionSummaryCached': summary_cached,
				'cached': True,
			})

	prompt = _build_scene_visual_guide_prompt(section, section_summary, section_text, scene)
	try:
		raw_guide = _call_gemini_scene_visual_guide(prompt, pid, section, scene_num)
	except RuntimeError as exc:
		return jsonify({'error': str(exc)}), 500
	except Exception as exc:
		logger.exception("[P4 scene_visual_guide] Gemini failed job=%s section=%s scene=%s", pid, section, scene_num)
		return jsonify({'error': f'No se pudo generar la guía visual de la escena: {exc}'}), 502

	guide = raw_guide.strip()
	if not guide:
		return jsonify({'error': 'Gemini no devolvió una guía visual válida.'}), 502

	existing_output[cache_key] = {
		'section': section,
		'sceneNum': scene_num,
		'contextHash': context_hash,
		'guide': guide,
		'generatedAt': time.time(),
	}
	_save_state(guide_state, {'status': 'completed', 'output': existing_output})

	return jsonify({
		'section': section,
		'sceneNum': scene_num,
		'guide': guide,
		'sectionSummary': section_summary,
		'sectionSummaryCached': summary_cached,
		'cached': False,
	})


@proceso4_bp.route('/jobs/<int:pid>/prompt-station/generate', methods=['POST'])
def generate_prompt_station(pid: int):
	"""Generate prompt-station data for one section and one variant."""
	get_or_create_job(pid)
	body = request.get_json(force=True) or {}
	section = body.get('section', '').strip()
	variant = str(body.get('variant') or 'metadata').strip().lower()
	if not section:
		return jsonify({'error': "El campo 'section' es requerido."}), 400
	if variant not in {'metadata', 'final'}:
		return jsonify({'error': "El campo 'variant' debe ser 'metadata' o 'final'."}), 400

	scenes = _get_imported_scenes(pid)
	section_scenes = [s for s in scenes if s.get('section') == section]
	if not section_scenes:
		return jsonify({'error': f"No hay escenas para la sección '{section}'."}), 404

	tema_principal = _get_tema_principal(pid)
	estilo_canal = _get_estilo_canal(pid)
	visual_briefs = _generate_visual_briefs_for_section(
		pid=pid,
		section=section,
		section_scenes=section_scenes,
		tema_principal=tema_principal,
	)

	result: list[dict] = []
	for scene in section_scenes:
		sn = scene.get('scene_num', 0)
		seccion_actual = section
		narracion = str(scene.get('text', ''))
		concepto = str(scene.get('visual_description', ''))
		tipo_visual = str(scene.get('visual_type', 'Animation'))
		duracion = float(scene.get('duration', 5.0))
		physical_comp = str(scene.get('physical_composition', ''))
		visual_brief = visual_briefs.get(
			int(sn),
			_reinforce_title_anchor(scene, tema_principal, _fallback_visual_brief(scene, tema_principal)),
		)
		base_payload = {
			'scene_num': sn,
			'section': section,
			'duration': duracion,
			'text': narracion,
			'visual_type': tipo_visual,
			'visual_description': concepto,
			'physical_composition': physical_comp,
			'visual_brief': visual_brief,
		}

		if variant == 'metadata':
			t2v = build_text_to_video_prompt(
				tema_principal=tema_principal,
				seccion_actual=seccion_actual,
				estilo_canal=estilo_canal,
				narracion_escena=narracion,
				concepto_visual_base=concepto,
				tipo_visual=tipo_visual,
				duracion_segundos=duracion,
				physical_composition=physical_comp,
			)
			t2i = build_text_to_image_prompt(
				tema_principal=tema_principal,
				seccion_actual=seccion_actual,
				estilo_canal=estilo_canal,
				narracion_escena=narracion,
				concepto_visual_base=concepto,
				tipo_visual=tipo_visual,
				duracion_segundos=duracion,
				physical_composition=physical_comp,
				visual_brief=visual_brief,
			)
			i2v = build_image_to_video_prompt(
				tema_principal=tema_principal,
				seccion_actual=seccion_actual,
				estilo_canal=estilo_canal,
				narracion_escena=narracion,
				concepto_visual_base=concepto,
				tipo_visual=tipo_visual,
				duracion_segundos=duracion,
				physical_composition=physical_comp,
			)
			t2a = build_text_to_animation_prompt(
				tema_principal=tema_principal,
				seccion_actual=seccion_actual,
				estilo_canal=estilo_canal,
				narracion_escena=narracion,
				concepto_visual_base=concepto,
				tipo_visual=tipo_visual,
				duracion_segundos=duracion,
				physical_composition=physical_comp,
				visual_brief=visual_brief,
			)
			result.append({
				**base_payload,
				'text_to_video_prompt': t2v,
				'text_to_image_prompt_metadata': t2i,
				'text_to_image_prompt': t2i,
				'image_to_video_prompt': i2v,
				'text_to_animation_prompt': t2a,
			})
		else:
			final_prompt = build_text_to_image_final_prompt(
				tema_principal=tema_principal,
				seccion_actual=seccion_actual,
				estilo_canal=estilo_canal,
				narracion_escena=narracion,
				concepto_visual_base=concepto,
				tipo_visual=tipo_visual,
				physical_composition=physical_comp,
				visual_brief=visual_brief,
			)
			result.append({
				**base_payload,
				**final_prompt,
			})

	# Persist to subprocess state
	ps_state = get_or_create_subprocess_state(pid, 'prompt_station')
	existing_output = dict(ps_state.output_payload or {})
	existing_variants = _normalize_prompt_station_variants(existing_output.get(section))
	existing_variants[variant] = result
	existing_output[section] = existing_variants
	_save_state(ps_state, {'status': 'completed', 'output': existing_output})

	return jsonify({
		'section': section,
		'variant': variant,
		'sceneCount': len(result),
		'scenes': result,
	})
