"""
Audio Processor — Manejo de audio: velocidad (ffmpeg atempo) y concatenación con markers.
Proceso 2: Pipeline de audio para video.
"""
import subprocess
import os
import sys
import json
from datetime import datetime
from pathlib import Path


KNOWN_GOOD_FFMPEG_PACKAGE = "ffmpeg-7.0.2-gpl_h9cf63cc_102"
KNOWN_BAD_BINARY_PARTS = (
    "ffmpeg-8.0.1-gpl_hb2d76f6_912",
    r"envs\scienceluxe\Library\bin",
)


def _is_known_bad_binary(path: str) -> bool:
    normalized = path.lower().replace("/", "\\")
    return any(part.lower() in normalized for part in KNOWN_BAD_BINARY_PARTS)


def _get_conda_base() -> Path:
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        return Path(conda_prefix).parent.parent
    return Path.home() / "miniconda3"


def _get_env_binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe without touching broken Conda binaries."""
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            path = imageio_ffmpeg.get_ffmpeg_exe()
            if path and os.path.exists(path) and not _is_known_bad_binary(path):
                return path
        except ImportError:
            pass

    env_var = f"{name.upper()}_BIN"
    explicit = os.environ.get(env_var, "").strip()
    if explicit and os.path.exists(explicit) and not _is_known_bad_binary(explicit):
        return explicit

    known_good = _get_conda_base() / "pkgs" / KNOWN_GOOD_FFMPEG_PACKAGE / "Library" / "bin" / f"{name}.exe"
    if known_good.exists():
        return str(known_good)

    import shutil
    on_path = shutil.which(name)
    if on_path and not _is_known_bad_binary(on_path):
        return on_path

    return name


def _get_ffmpeg_path() -> str:
    """Encuentra el ejecutable ffmpeg."""
    resolved = _get_env_binary("ffmpeg")
    if resolved != "ffmpeg":
        return resolved

    # Option 1: imageio-ffmpeg (bundled, self-contained, always works)
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except ImportError:
        pass

    # Option 2: system PATH
    for name in ["ffmpeg", "ffmpeg.exe"]:
        try:
            result = subprocess.run(
                [name, "-version"], capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Option 3: conda env Library/bin
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        candidate = os.path.join(conda_prefix, "Library", "bin", "ffmpeg.exe")
        if os.path.exists(candidate):
            return candidate

    return "ffmpeg"  # fallback


# Cache the resolved path
_FFMPEG = None
_FFPROBE = None

def _ffmpeg():
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _get_ffmpeg_path()
    return _FFMPEG


def _ffprobe():
    global _FFPROBE
    if _FFPROBE is None:
        _FFPROBE = _get_env_binary("ffprobe")
    return _FFPROBE


def check_ffmpeg() -> bool:
    """Verifica que ffmpeg esté disponible en el sistema."""
    try:
        result = subprocess.run(
            [_ffmpeg(), "-version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_audio_duration(filepath: str) -> float:
    """Obtiene la duracion de un archivo de audio en segundos usando ffprobe explicito."""
    try:
        result = subprocess.run(
            [
                _ffprobe(),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    # Fallback: parse duration from ffmpeg stderr
    try:
        import re
        result = subprocess.run(
            [_ffmpeg(), "-i", filepath, "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100
    except Exception:
        pass
    return 0.0


def speed_up_audio(input_path: str, output_path: str, speed: float = 1.05) -> dict:
    """
    Acelera audio sin cambiar pitch usando ffmpeg atempo (WSOLA).
    
    Returns dict con info del procesamiento.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"No se encontró: {input_path}")

    duration_before = get_audio_duration(input_path)

    cmd = [
        _ffmpeg(), "-y", "-i", input_path,
        "-filter:a", f"atempo={speed}",
        "-vn", output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")

    duration_after = get_audio_duration(output_path)

    return {
        "input": input_path,
        "output": output_path,
        "speed": speed,
        "duration_before": round(duration_before, 2),
        "duration_after": round(duration_after, 2),
        "saved_seconds": round(duration_before - duration_after, 2),
    }


def concatenate_with_markers(
    audio_paths: list,
    labels: list,
    output_path: str,
    transition_ms: int = 2500,
) -> dict:
    """
    Concatena múltiples audios con silencio entre ellos.
    Genera markers JSON con timestamps de inicio/fin de cada sección.
    
    Usa ffmpeg para concatenación precisa.
    """
    if len(audio_paths) != len(labels):
        raise ValueError("audio_paths y labels deben tener la misma longitud")

    # Obtener duraciones
    durations = []
    for path in audio_paths:
        dur = get_audio_duration(path)
        if dur <= 0:
            raise ValueError(f"No se pudo obtener duración de: {path}")
        durations.append(dur)

    # Calcular markers
    markers = {}
    current_pos = 0.0
    transition_sec = transition_ms / 1000.0

    for i, (label, duration) in enumerate(zip(labels, durations)):
        markers[label] = {
            "start": round(current_pos, 3),
            "end": round(current_pos + duration, 3),
            "duration": round(duration, 3),
        }
        current_pos += duration
        if i < len(labels) - 1:
            current_pos += transition_sec

    total_duration = current_pos
    markers["_total"] = round(total_duration, 3)
    markers["_transition_ms"] = transition_ms

    # Crear archivo de lista para ffmpeg concat
    temp_dir = os.path.dirname(output_path)
    list_file = os.path.join(temp_dir, "_concat_list.txt")
    silence_file = os.path.join(temp_dir, "_silence.wav")

    # Generar silencio
    cmd_silence = [
        _ffmpeg(), "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", str(transition_sec),
        silence_file,
    ]
    subprocess.run(cmd_silence, capture_output=True, timeout=30)

    # Convertir todos a WAV con mismo formato para concat limpio
    wav_files = []
    for i, path in enumerate(audio_paths):
        wav_path = os.path.join(temp_dir, f"_part_{i}.wav")
        cmd_convert = [
            _ffmpeg(), "-y", "-i", path,
            "-ar", "44100", "-ac", "1", wav_path,
        ]
        subprocess.run(cmd_convert, capture_output=True, timeout=60)
        wav_files.append(wav_path)

    # Escribir lista de concat
    with open(list_file, "w") as f:
        for i, wav_path in enumerate(wav_files):
            f.write(f"file '{wav_path}'\n")
            if i < len(wav_files) - 1:
                f.write(f"file '{silence_file}'\n")

    # Concatenar
    cmd_concat = [
        _ffmpeg(), "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:a", "libmp3lame", "-b:a", "192k",
        output_path,
    ]
    result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat error: {result.stderr[-500:]}")

    # Limpiar archivos temporales
    for f in wav_files:
        try:
            os.remove(f)
        except Exception:
            pass
    for f in [list_file, silence_file]:
        try:
            os.remove(f)
        except Exception:
            pass

    # Guardar markers JSON
    markers_path = output_path.replace(".mp3", "_markers.json")
    with open(markers_path, "w", encoding="utf-8") as f:
        json.dump(markers, f, indent=2, ensure_ascii=False)

    return {
        "output": output_path,
        "markers_path": markers_path,
        "markers": markers,
        "total_duration": round(total_duration, 2),
        "num_parts": len(audio_paths),
        "transition_ms": transition_ms,
    }


def format_duration(seconds: float) -> str:
    """Formatea segundos a mm:ss."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"
