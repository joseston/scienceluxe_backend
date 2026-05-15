"""
SRT Generator — Genera subtítulos SRT con timestamps precisos.
Proceso 2, Subproceso 4.

Usa faster-whisper (CTranslate2) con modelo large-v2 int8 para:
- Máxima calidad de transcripción (~8% WER español)
- Solo ~3GB VRAM (compatible con RTX 4050 6GB)
- Word-level timestamps nativos
- 4x más rápido que whisper original
"""
import os
import json


def format_srt_timestamp(seconds: float) -> str:
    """Convierte segundos a formato SRT: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def check_whisper_status() -> dict:
    """Verifica disponibilidad de Whisper y GPU."""
    status = {
        "whisper": False,
        "gpu": False,
        "gpu_name": "",
        "vram_gb": 0,
        "device": "cpu",
        "engine": "none",
        "model": "large-v2",
        "quantization": "int8",
    }

    # Verificar faster-whisper (preferido)
    try:
        import faster_whisper
        status["whisper"] = True
        status["engine"] = "faster-whisper"
    except ImportError:
        # Fallback a whisper-timestamped / openai-whisper
        try:
            import whisper_timestamped
            status["whisper"] = True
            status["engine"] = "whisper-timestamped"
            status["model"] = "small"  # safer for VRAM with original whisper
            status["quantization"] = "fp16"
        except ImportError:
            try:
                import whisper
                status["whisper"] = True
                status["engine"] = "openai-whisper"
                status["model"] = "small"
                status["quantization"] = "fp16"
            except ImportError:
                pass

    # Verificar GPU
    try:
        import torch
        if torch.cuda.is_available():
            status["gpu"] = True
            status["gpu_name"] = torch.cuda.get_device_name(0)
            status["vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1024**3, 1
            )
            status["device"] = "cuda"
    except ImportError:
        pass

    return status


def _setup_ffmpeg():
    """Configura ffmpeg funcional en PATH (imageio-ffmpeg para Windows)."""
    try:
        import imageio_ffmpeg
        import tempfile, shutil

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        tmp_dir = os.path.join(tempfile.gettempdir(), "scienceluxe_ffmpeg")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_ffmpeg = os.path.join(tmp_dir, "ffmpeg.exe")
        if not os.path.exists(tmp_ffmpeg):
            shutil.copy2(ffmpeg_exe, tmp_ffmpeg)
            print(f"   🔧 ffmpeg copiado a: {tmp_dir}")
        os.environ["PATH"] = tmp_dir + os.pathsep + os.environ.get("PATH", "")
        print(f"   🔧 PATH actualizado con ffmpeg funcional")
    except Exception as ex:
        print(f"   ⚠️ No se pudo configurar ffmpeg: {ex}")


def generate_srt_whisper(audio_path: str, output_srt: str, language: str = "es") -> dict:
    """
    Genera SRT con timestamps precisos.

    Estrategia de motores (en orden de prioridad):
    1. faster-whisper + large-v2 int8 (~3GB VRAM, mejor calidad)
    2. whisper-timestamped + small (~2GB VRAM, fallback)
    3. openai-whisper + small (~2GB VRAM, último recurso)

    Returns dict con resultado e info.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio no encontrado: {audio_path}")

    # Setup ffmpeg para que Whisper lo encuentre
    _setup_ffmpeg()

    segments = []

    # ─── OPCIÓN 1: faster-whisper (PREFERIDO) ───
    try:
        from faster_whisper import WhisperModel

        # Detectar device
        device = "cpu"
        compute_type = "int8"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                compute_type = "int8_float16"  # Mejor rendimiento en GPU
                gpu_name = torch.cuda.get_device_name(0)
                vram_free = round(torch.cuda.mem_get_info()[0] / 1024**3, 1)
                print(f"   🎮 GPU: {gpu_name} ({vram_free} GB libres)")
                print(f"   ⚡ Usando CUDA — transcripción acelerada")
        except ImportError:
            pass

        model_name = "large-v2"
        print(f"   📦 faster-whisper — modelo '{model_name}' ({compute_type})")
        print(f"   ⏳ Cargando modelo en {device}... (primera vez descarga ~1.5GB)")

        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )

        print(f"   🎙  Transcribiendo audio con word-level timestamps...")

        result_segments, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=5,
            vad_filter=True,  # Filtra silencios, evita alucinaciones
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        for seg in result_segments:
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": [
                    {"word": w.word.strip(), "start": w.start, "end": w.end}
                    for w in (seg.words or [])
                ],
            })

        print(f"   ✅ Transcripción completa: {len(segments)} segmentos")
        print(f"   📊 Idioma detectado: {info.language} (prob: {info.language_probability:.1%})")
        print(f"   📊 Duración: {info.duration:.1f}s")

    except ImportError:
        # ─── OPCIÓN 2: whisper-timestamped (FALLBACK) ───
        try:
            import whisper_timestamped as whisper

            device = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    print(f"   🎮 GPU detectada, usando CUDA")
            except ImportError:
                pass

            model_name = "small"  # Seguro para VRAM con whisper original
            print(f"   📦 whisper-timestamped — modelo '{model_name}'")
            print(f"   ⏳ Cargando modelo en {device}...")
            model = whisper.load_model(model_name, device=device)
            print(f"   🎙  Transcribiendo audio...")
            result = whisper.transcribe(model, audio_path, language=language)

            for seg in result["segments"]:
                segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                })

            print(f"   ✅ Transcripción completa: {len(segments)} segmentos")

        except ImportError:
            # ─── OPCIÓN 3: openai-whisper (ÚLTIMO RECURSO) ───
            try:
                import whisper

                device = "cpu"
                try:
                    import torch
                    if torch.cuda.is_available():
                        device = "cuda"
                except ImportError:
                    pass

                model_name = "small"
                print(f"   📦 openai-whisper — modelo '{model_name}'")
                print(f"   ⏳ Cargando modelo en {device}...")
                model = whisper.load_model(model_name, device=device)
                print(f"   🎙  Transcribiendo audio...")
                result = model.transcribe(audio_path, language=language)

                for seg in result["segments"]:
                    segments.append({
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": seg["text"].strip(),
                    })

                print(f"   ✅ Transcripción completa: {len(segments)} segmentos")

            except ImportError:
                raise ImportError(
                    "Se requiere faster-whisper, whisper-timestamped u openai-whisper.\n"
                    "Instalar: pip install faster-whisper\n"
                    "O: pip install whisper-timestamped"
                )

    # Escribir SRT
    with open(output_srt, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start_ts = format_srt_timestamp(seg["start"])
            end_ts = format_srt_timestamp(seg["end"])
            f.write(f"{i}\n{start_ts} --> {end_ts}\n{seg['text']}\n\n")

    # Guardar también como JSON para procesamiento posterior
    json_path = output_srt.replace(".srt", "_segments.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)

    return {
        "srt_path": output_srt,
        "json_path": json_path,
        "segments": segments,
        "num_segments": len(segments),
        "total_duration": segments[-1]["end"] if segments else 0,
    }


def parse_srt_file(srt_path: str) -> list:
    """Parsea un archivo SRT existente a lista de segmentos."""
    segments = []
    if not os.path.exists(srt_path):
        return segments

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            timestamps = lines[1].split(" --> ")
            if len(timestamps) == 2:
                text = " ".join(lines[2:])
                segments.append({
                    "start": _parse_srt_time(timestamps[0].strip()),
                    "end": _parse_srt_time(timestamps[1].strip()),
                    "text": text.strip(),
                })

    return segments


def _parse_srt_time(time_str: str) -> float:
    """Parsea HH:MM:SS,mmm a segundos."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds
