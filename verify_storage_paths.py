from __future__ import annotations

import json
import os
from pathlib import Path

from aplicacion import create_app, db
from aplicacion.models.clip_library import ClipLibraryItem
from aplicacion.models.proceso1 import Proceso1Job
from aplicacion.models.proceso2 import Proceso2SubprocessState
from aplicacion.models.proceso2_corto import Proceso2CortoSubprocessState
from aplicacion.models.proceso4 import (
    Proceso4AudioTrack,
    Proceso4GlobalAsset,
    Proceso4SceneMedia,
    Proceso4SectionTrack,
    Proceso4SubprocessState,
)
from aplicacion.models.proceso4_corto import Proceso4CortoAudioTrack, Proceso4CortoSceneMedia

WIN_CLIP_ROOT = r'H:\Mi unidad\Scienceluxe_clips'
WIN_STORAGE_ROOT = r'D:\scienceluxe_2026'
WIN_DATA_ROOT = r'C:\Users\JOSE\Escritorio\Scienceluxe\Aplicacion Scienceluxe Videos Largos\data'


def _repo_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / 'data'


def _storage_root() -> Path:
    return Path(os.environ.get('STORAGE_ROOT', str(Path.home() / 'scienceluxe_2026')))


def _clips_root() -> Path:
    return Path(
        os.environ.get(
            'CLIPS_LIBRARY_DIR',
            str(Path.home() / 'GoogleDrive' / 'Scienceluxe_clips'),
        )
    )


def _get_video_id(proceso1_job_id: int) -> str:
    try:
        import re
        job = Proceso1Job.query.get(proceso1_job_id)
        if job and job.video_id:
            return re.sub(r'[^A-Za-z0-9_\-]', '_', str(job.video_id))[:60]
    except Exception:
        pass
    return str(proceso1_job_id)


def _p4_storage_job_dir(proceso1_job_id: int) -> Path:
    return _storage_root() / f'job_{proceso1_job_id}_{_get_video_id(proceso1_job_id)}' / 'proceso4'


def _map_proceso4_job_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None

    raw = str(raw_path)
    norm = raw.replace("\\", "/")
    prefixes = [
        str(_repo_data_dir() / 'proceso4').replace("\\", "/"),
        f"{WIN_DATA_ROOT.replace('\\', '/')}/proceso4",
    ]
    for prefix in prefixes:
        marker = f"{prefix}/"
        if not norm.startswith(marker):
            continue
        rest = norm[len(marker):]
        parts = rest.split("/")
        if not parts or not parts[0].isdigit():
            return Path(raw)
        pid = int(parts[0])
        rel = Path("/".join(parts[1:])) if len(parts) > 1 else Path()
        return _p4_storage_job_dir(pid) / rel

    return None


def _map_legacy_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None

    raw = str(raw_path)
    p4_mapped = _map_proceso4_job_path(raw)
    if p4_mapped is not None:
        return p4_mapped

    if raw.startswith(WIN_CLIP_ROOT):
        rel = raw[len(WIN_CLIP_ROOT):].lstrip("\\/")
        return _clips_root() / Path(rel.replace("\\", "/"))
    if raw.startswith(WIN_STORAGE_ROOT):
        rel = raw[len(WIN_STORAGE_ROOT):].lstrip("\\/")
        return _storage_root() / Path(rel.replace("\\", "/"))
    if raw.startswith(WIN_DATA_ROOT):
        rel = raw[len(WIN_DATA_ROOT):].lstrip("\\/")
        return _repo_data_dir() / Path(rel.replace("\\", "/"))
    return Path(raw)


def _prefix(raw_path: str | None) -> str:
    if not raw_path:
        return "<null>"
    raw = str(raw_path)
    if ":\\" in raw:
        return raw.split("\\", 1)[0]
    return raw.split("/", 1)[0]


def _summarize(name: str, rows: list[tuple[int | str, str | None]]) -> dict:
    prefixes: dict[str, int] = {}
    missing_examples: list[dict[str, str | int]] = []
    total = len(rows)
    existing = 0

    for row_id, raw_path in rows:
        mapped = _map_legacy_path(raw_path)
        prefixes[_prefix(raw_path)] = prefixes.get(_prefix(raw_path), 0) + 1
        if mapped and mapped.exists():
            existing += 1
        elif len(missing_examples) < 8:
            missing_examples.append(
                {
                    "id": row_id,
                    "raw": raw_path,
                    "mapped": str(mapped) if mapped else "",
                }
            )

    return {
        "name": name,
        "total": total,
        "mapped_exists": existing,
        "mapped_missing": total - existing,
        "prefixes": prefixes,
        "missing_examples": missing_examples,
    }


def main() -> None:
    app = create_app()
    with app.app_context():
        reports = [
            _summarize(
                "proceso4_scene_media.file_path",
                [(row.id, row.file_path) for row in Proceso4SceneMedia.query.all()],
            ),
            _summarize(
                "proceso4_scene_media.proxy_path",
                [(row.id, row.proxy_path) for row in Proceso4SceneMedia.query.filter(Proceso4SceneMedia.proxy_path.isnot(None)).all()],
            ),
            _summarize(
                "proceso4_audio_tracks.file_path",
                [(row.id, row.file_path) for row in Proceso4AudioTrack.query.all()],
            ),
            _summarize(
                "proceso4_section_tracks.pista_path",
                [(row.id, row.pista_path) for row in Proceso4SectionTrack.query.all()],
            ),
            _summarize(
                "proceso4_global_assets.file_path",
                [(row.id, row.file_path) for row in Proceso4GlobalAsset.query.all()],
            ),
            _summarize(
                "clip_library_items.file_path",
                [(row.id, row.file_path) for row in ClipLibraryItem.query.all()],
            ),
            _summarize(
                "clip_library_items.thumbnail_path",
                [(row.id, row.thumbnail_path) for row in ClipLibraryItem.query.filter(ClipLibraryItem.thumbnail_path.isnot(None)).all()],
            ),
            _summarize(
                "clip_library_items.proxy_path",
                [(row.id, row.proxy_path) for row in ClipLibraryItem.query.filter(ClipLibraryItem.proxy_path.isnot(None)).all()],
            ),
            _summarize(
                "proceso4_corto_scene_media.file_path",
                [(row.id, row.file_path) for row in Proceso4CortoSceneMedia.query.all()],
            ),
            _summarize(
                "proceso4_corto_scene_media.proxy_path",
                [(row.id, row.proxy_path) for row in Proceso4CortoSceneMedia.query.filter(Proceso4CortoSceneMedia.proxy_path.isnot(None)).all()],
            ),
            _summarize(
                "proceso4_corto_audio_tracks.file_path",
                [(row.id, row.file_path) for row in Proceso4CortoAudioTrack.query.all()],
            ),
        ]

        p2_rows = []
        for row in Proceso2SubprocessState.query.all():
            payload = row.output_payload or {}
            if payload.get("finalMp3"):
                p2_rows.append((row.proceso1_job_id, payload["finalMp3"]))
        reports.append(_summarize("proceso2_subprocess_states.output.finalMp3", p2_rows))

        p2c_rows = []
        for row in Proceso2CortoSubprocessState.query.all():
            payload = row.output_payload or {}
            candidate = payload.get("speedFile") or payload.get("audioPath")
            if candidate:
                p2c_rows.append((row.proceso1_corto_job_id, candidate))
        reports.append(_summarize("proceso2_corto_subprocess_states.output audio", p2c_rows))

        p4_render_rows = []
        for row in Proceso4SubprocessState.query.all():
            payload = row.output_payload or {}
            if payload.get("videoPath"):
                p4_render_rows.append((row.proceso1_job_id, payload["videoPath"]))
        reports.append(_summarize("proceso4_subprocess_states.output.videoPath", p4_render_rows))

        print(json.dumps(reports, indent=2, ensure_ascii=False))
        db.session.remove()


if __name__ == "__main__":
    main()
