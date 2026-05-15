"""
Subtitle Generator Corto — Genera SRT optimizado para videos cortos verticales.

Toma los segmentos con word-level timestamps de Whisper (final_segments.json
generado en Proceso 2 Corto) y produce un SRT con chunks cortos (~40 chars max)
ideales para subtítulos en pantalla vertical (9:16).

Reglas de chunking:
  - Max ~42 caracteres por subtítulo (pantalla vertical 9:16 es estrecha)
  - Cortar en pausas naturales: comas, puntos, conjunciones
  - Duración mínima ~0.8s, máxima ~4.5s
  - No dividir a mitad de palabra
"""
import json
import re
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_CHARS = 42          # Max characters per subtitle line
MIN_DURATION = 0.8      # Min seconds a subtitle should last
MAX_DURATION = 4.5      # Max seconds before forcing a split
NATURAL_BREAKS = {',', ';', ':', '—', '–', '...'}
CONJUNCTIONS = {'que', 'pero', 'y', 'o', 'porque', 'cuando', 'donde', 'como',
                'si', 'para', 'por', 'con', 'sin', 'ni', 'pues', 'ya',
                'that', 'but', 'and', 'or', 'because', 'when', 'where',
                'how', 'if', 'for', 'with', 'without'}


def format_srt_timestamp(seconds: float) -> str:
    """Converts seconds to SRT format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# Core chunking
# ─────────────────────────────────────────────────────────────────────────────

def _is_natural_break(word: str) -> bool:
    """Check if a word ends with a natural break character."""
    stripped = word.rstrip()
    if not stripped:
        return False
    if stripped[-1] in {'.', '!', '?'}:
        return True
    for ch in NATURAL_BREAKS:
        if stripped.endswith(ch):
            return True
    return False


def _is_conjunction(word: str) -> bool:
    """Check if a word is a conjunction (good place to start a new chunk)."""
    clean = re.sub(r'[^a-záéíóúñü]', '', word.lower())
    return clean in CONJUNCTIONS


def _chunk_words(words: list[dict], max_chars: int = MAX_CHARS) -> list[list[dict]]:
    """
    Split a list of words (with timestamps) into subtitle chunks.

    Each chunk is a list of word dicts: {word, start, end}.
    Splitting strategy:
      1. Accumulate words until we exceed max_chars
      2. When over the limit, backtrack to the best split point:
         a. After a natural break (comma, period, etc.)
         b. Before a conjunction
         c. At the midpoint if no good break found
      3. Enforce MAX_DURATION: if a chunk exceeds it, force-split
    """
    if not words:
        return []

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0

    for i, w in enumerate(words):
        word_text = w.get('word', '').strip()
        if not word_text:
            continue

        # Length including space separator
        added_len = len(word_text) + (1 if current else 0)

        # Check if adding this word would exceed the limit
        if current and (current_len + added_len > max_chars):
            # Try to find a good split point within current
            best_split = _find_best_split(current)
            if best_split is not None and best_split > 0:
                chunks.append(current[:best_split])
                leftover = current[best_split:]
                current = leftover + [w]
                current_len = sum(len(ww.get('word', '').strip()) + 1 for ww in current) - 1
            else:
                # No good split — flush current, start new
                chunks.append(current)
                current = [w]
                current_len = len(word_text)
        else:
            current.append(w)
            current_len += added_len

        # Enforce MAX_DURATION on the current chunk
        if current and len(current) >= 2:
            chunk_duration = float(current[-1].get('end', 0)) - float(current[0].get('start', 0))
            if chunk_duration > MAX_DURATION:
                best_split = _find_best_split(current)
                if best_split is not None and best_split > 0 and best_split < len(current):
                    chunks.append(current[:best_split])
                    current = current[best_split:]
                    current_len = sum(len(ww.get('word', '').strip()) + 1 for ww in current) - 1

        # If the current word is a sentence-end, flush the chunk
        if _is_natural_break(word_text) and word_text[-1] in {'.', '!', '?'}:
            if current:
                chunks.append(current)
                current = []
                current_len = 0

    if current:
        chunks.append(current)

    # Merge very short chunks with neighbors
    chunks = _merge_short_chunks(chunks)

    return chunks


def _find_best_split(words: list[dict]) -> int | None:
    """
    Find the best split point within a list of words.
    Returns the index to split AT (i.e., words[:idx] is the first chunk).
    Priority:
      1. After a natural break (comma, period, semicolon)
      2. Before a conjunction
      3. Midpoint
    """
    if len(words) <= 1:
        return None

    # Look for natural breaks from the middle outward
    mid = len(words) // 2
    best = None
    best_distance = len(words)

    for i in range(len(words) - 1):
        word_text = words[i].get('word', '').strip()
        if _is_natural_break(word_text):
            dist = abs(i + 1 - mid)
            if dist < best_distance:
                best = i + 1
                best_distance = dist

    if best is not None:
        return best

    # Look for conjunctions (split BEFORE the conjunction)
    for i in range(1, len(words)):
        word_text = words[i].get('word', '').strip()
        if _is_conjunction(word_text):
            dist = abs(i - mid)
            if dist < best_distance:
                best = i
                best_distance = dist

    if best is not None:
        return best

    # Fallback: midpoint
    return mid


def _merge_short_chunks(chunks: list[list[dict]]) -> list[list[dict]]:
    """Merge chunks that are too short (< MIN_DURATION) with neighbors."""
    if len(chunks) <= 1:
        return chunks

    merged: list[list[dict]] = []
    for chunk in chunks:
        if not chunk:
            continue
        chunk_duration = float(chunk[-1].get('end', 0)) - float(chunk[0].get('start', 0))
        chunk_text = ' '.join(w.get('word', '').strip() for w in chunk)

        # If too short and we have a previous chunk, try merging
        if chunk_duration < MIN_DURATION and len(chunk_text) < MAX_CHARS // 2 and merged:
            prev = merged[-1]
            combined_text = ' '.join(w.get('word', '').strip() for w in prev + chunk)
            if len(combined_text) <= MAX_CHARS + 5:  # Allow slight overflow for merges
                merged[-1] = prev + chunk
                continue

        merged.append(chunk)

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Main API
# ─────────────────────────────────────────────────────────────────────────────

def generate_subtitles_from_segments(
    segments: list[dict],
    max_chars: int = MAX_CHARS,
) -> list[dict]:
    """
    Generate optimized subtitle entries from Whisper segments with word-level timestamps.

    Args:
        segments: list of Whisper segments, each with {start, end, text, words: [{word, start, end}]}
        max_chars: max characters per subtitle line

    Returns:
        list of subtitle dicts: {num, start, end, text, duration}
    """
    # Flatten all words from all segments
    all_words = []
    for seg in segments:
        words = seg.get('words')
        if words:
            for w in words:
                word_text = w.get('word', '').strip()
                if word_text:
                    all_words.append({
                        'word': word_text,
                        'start': float(w.get('start', 0)),
                        'end': float(w.get('end', 0)),
                    })
        elif seg.get('text', '').strip():
            # Fallback: treat the entire segment text as one "word"
            all_words.append({
                'word': seg['text'].strip(),
                'start': float(seg.get('start', 0)),
                'end': float(seg.get('end', 0)),
            })

    if not all_words:
        return []

    # Chunk the words
    chunks = _chunk_words(all_words, max_chars=max_chars)

    # Build subtitle entries
    subtitles = []
    for i, chunk in enumerate(chunks, start=1):
        if not chunk:
            continue
        text = ' '.join(w['word'] for w in chunk)
        start = chunk[0]['start']
        end = chunk[-1]['end']
        duration = round(end - start, 3)

        subtitles.append({
            'num': i,
            'start': round(start, 3),
            'end': round(end, 3),
            'text': text,
            'duration': duration,
        })

    return subtitles


def export_srt(subtitles: list[dict], output_path: str) -> str:
    """Write subtitle entries to an SRT file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        for sub in subtitles:
            start_ts = format_srt_timestamp(sub['start'])
            end_ts = format_srt_timestamp(sub['end'])
            f.write(f"{sub['num']}\n{start_ts} --> {end_ts}\n{sub['text']}\n\n")
    return output_path


def get_subtitle_stats(subtitles: list[dict]) -> dict:
    """Calculate statistics about the generated subtitles."""
    if not subtitles:
        return {'total': 0}

    durations = [s['duration'] for s in subtitles]
    char_counts = [len(s['text']) for s in subtitles]

    return {
        'total': len(subtitles),
        'totalDuration': round(subtitles[-1]['end'] - subtitles[0]['start'], 2),
        'avgDuration': round(sum(durations) / len(durations), 2),
        'minDuration': round(min(durations), 2),
        'maxDuration': round(max(durations), 2),
        'avgChars': round(sum(char_counts) / len(char_counts), 1),
        'maxChars': max(char_counts),
        'subtitlesOverLimit': sum(1 for c in char_counts if c > MAX_CHARS),
    }
