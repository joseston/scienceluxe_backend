"""Embedding and keyword extraction service for the Clip Library.

Uses Gemini gemini-embedding-001 (3072-dim, or 768-dim with output_dimensionality)
via the new google-genai SDK for semantic vector search.
"""

import logging
import re
from typing import Optional

from google import genai
from google.genai import types as genai_types
from flask import current_app

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Stopwords (EN + ES) — lightweight, no extra dependency             #
# ------------------------------------------------------------------ #

_STOPWORDS = frozenset(
	"a an the and or but in on at to for of is it that this with from by as are was were be been "
	"being have has had do does did will would shall should may might can could not no nor so if "
	"then than too very just also about up out into over after before between through during "
	# Spanish
	"el la los las un una unos unas de del al y o pero en por para con sin sobre entre como más "
	"que se lo le su sus es son fue era ser estar ha hay no sí muy ya también desde hasta donde "
	"cuando porque aunque cada todo toda todos todas otro otra otros otras este esta estos estas "
	"ese esa esos esas aquel aquella aquellos aquellas".split()
)

# Embedding dimensions — gemini-embedding-001 defaults to 3072 dims,
# we request 768 to maintain pgvector column compatibility.
_EMBEDDING_DIM = 768
_EMBEDDING_MODEL = "models/gemini-embedding-001"


# ------------------------------------------------------------------ #
#  Client factory                                                      #
# ------------------------------------------------------------------ #

def _get_client() -> genai.Client:
	"""Create a Gemini client using the configured API key."""
	api_key = current_app.config.get('GEMINI_API_KEY', '')
	if not api_key:
		raise RuntimeError("GEMINI_API_KEY not configured")
	return genai.Client(api_key=api_key)


# ------------------------------------------------------------------ #
#  Embedding generation                                               #
# ------------------------------------------------------------------ #

def generate_embedding(text: str) -> Optional[list[float]]:
	"""Generate a 768-dim embedding vector using Gemini gemini-embedding-001.

	Returns None if the text is empty or API fails.
	"""
	if not text or not text.strip():
		return None
	try:
		client = _get_client()
		result = client.models.embed_content(
			model=_EMBEDDING_MODEL,
			contents=text.strip()[:2048],
			config=genai_types.EmbedContentConfig(
				task_type="RETRIEVAL_DOCUMENT",
				output_dimensionality=_EMBEDDING_DIM,
			),
		)
		return list(result.embeddings[0].values)
	except Exception:
		logger.exception("Failed to generate embedding for text: %s...", text[:80])
		return None


def generate_query_embedding(text: str) -> Optional[list[float]]:
	"""Generate an embedding optimised for query/retrieval."""
	if not text or not text.strip():
		return None
	try:
		client = _get_client()
		result = client.models.embed_content(
			model=_EMBEDDING_MODEL,
			contents=text.strip()[:2048],
			config=genai_types.EmbedContentConfig(
				task_type="RETRIEVAL_QUERY",
				output_dimensionality=_EMBEDDING_DIM,
			),
		)
		return list(result.embeddings[0].values)
	except Exception:
		logger.exception("Failed to generate query embedding")
		return None


# ------------------------------------------------------------------ #
#  Keyword extraction                                                  #
# ------------------------------------------------------------------ #

def extract_keywords(
	visual_description: str = "",
	physical_composition: str = "",
	extra_text: str = "",
) -> list[str]:
	"""Extract meaningful keywords from combined metadata text.

	Tokenises and filters stopwords; returns lowercase unique keywords.
	"""
	combined = f"{visual_description} {physical_composition} {extra_text}"
	# Tokenise: keep alphanumeric + hyphens, min 3 chars
	tokens = re.findall(r"[a-záéíóúñü0-9][\w\-]{2,}", combined.lower())
	seen: set[str] = set()
	keywords: list[str] = []
	for tok in tokens:
		if tok not in _STOPWORDS and tok not in seen:
			seen.add(tok)
			keywords.append(tok)
	return keywords


# ------------------------------------------------------------------ #
#  Build combined search text for embedding                            #
# ------------------------------------------------------------------ #

def build_clip_text(
	visual_description: str = "",
	physical_composition: str = "",
	visual_type: str = "",
	keywords: list[str] | None = None,
) -> str:
	"""Build a single text blob for embedding generation from clip metadata."""
	parts = []
	if visual_type:
		parts.append(f"[{visual_type}]")
	if visual_description:
		parts.append(visual_description.strip())
	if physical_composition:
		parts.append(f"Objects: {physical_composition.strip()}")
	if keywords:
		parts.append(f"Keywords: {', '.join(keywords)}")
	return " | ".join(parts) if parts else ""
