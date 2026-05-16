from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
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


def _translate_proceso4_job_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return raw_path

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
            return raw
        pid = int(parts[0])
        rel = Path("/".join(parts[1:])) if len(parts) > 1 else Path()
        return str(_p4_storage_job_dir(pid) / rel)

    return raw


def _translate_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return raw_path

    p4_path = _translate_proceso4_job_path(raw_path)
    if p4_path != raw_path:
        return p4_path

    raw = str(raw_path)
    if raw.startswith(WIN_CLIP_ROOT):
        rel = raw[len(WIN_CLIP_ROOT):].lstrip("\\/")
        return str(_clips_root() / Path(rel.replace("\\", "/")))
    if raw.startswith(WIN_STORAGE_ROOT):
        rel = raw[len(WIN_STORAGE_ROOT):].lstrip("\\/")
        return str(_storage_root() / Path(rel.replace("\\", "/")))
    if raw.startswith(WIN_DATA_ROOT):
        rel = raw[len(WIN_DATA_ROOT):].lstrip("\\/")
        return str(_repo_data_dir() / Path(rel.replace("\\", "/")))
    return raw


def _backup_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _repo_data_dir() / "migration_backups" / f"storage_paths_{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dump_backup(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_attr(obj: object, attr: str, counters: dict[str, int], changes: list[dict], label: str) -> None:
    old = getattr(obj, attr)
    new = _translate_path(old)
    if old != new:
        setattr(obj, attr, new)
        counters["changes"] += 1
        if len(changes) < 20:
            changes.append({"table": label, "id": getattr(obj, "id", None), "field": attr, "old": old, "new": new})


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy Windows storage paths to Linux paths.")
    parser.add_argument("--apply", action="store_true", help="Persist changes to the database.")
    args = parser.parse_args()

    app = create_app()
    backups: dict[str, list[dict]] = {}
    counters = {"changes": 0}
    sample_changes: list[dict] = []

    with app.app_context():
        tables = [
            ("proceso4_scene_media", Proceso4SceneMedia, ["file_path", "proxy_path"]),
            ("proceso4_audio_tracks", Proceso4AudioTrack, ["file_path"]),
            ("proceso4_section_tracks", Proceso4SectionTrack, ["pista_path"]),
            ("proceso4_global_assets", Proceso4GlobalAsset, ["file_path"]),
            ("clip_library_items", ClipLibraryItem, ["file_path", "thumbnail_path", "proxy_path"]),
            ("proceso4_corto_scene_media", Proceso4CortoSceneMedia, ["file_path", "proxy_path"]),
            ("proceso4_corto_audio_tracks", Proceso4CortoAudioTrack, ["file_path"]),
        ]

        for table_name, model, fields in tables:
            rows = model.query.all()
            backups[table_name] = []
            for row in rows:
                backups[table_name].append(
                    {
                        "id": getattr(row, "id", None),
                        **{field: getattr(row, field) for field in fields},
                    }
                )
                for field in fields:
                    _update_attr(row, field, counters, sample_changes, table_name)

        backups["proceso2_subprocess_states"] = []
        for row in Proceso2SubprocessState.query.all():
            backups["proceso2_subprocess_states"].append(
                {
                    "id": row.id,
                    "proceso1_job_id": row.proceso1_job_id,
                    "subprocess_key": row.subprocess_key,
                    "output_payload": row.output_payload,
                }
            )
            payload = dict(row.output_payload or {})
            current = payload.get("finalMp3")
            updated = _translate_path(current)
            if current != updated:
                payload["finalMp3"] = updated
                row.output_payload = payload
                counters["changes"] += 1
                if len(sample_changes) < 20:
                    sample_changes.append(
                        {
                            "table": "proceso2_subprocess_states",
                            "id": row.id,
                            "field": "output_payload.finalMp3",
                            "old": current,
                            "new": updated,
                        }
                    )

        backups["proceso2_corto_subprocess_states"] = []
        for row in Proceso2CortoSubprocessState.query.all():
            backups["proceso2_corto_subprocess_states"].append(
                {
                    "id": row.id,
                    "proceso1_corto_job_id": row.proceso1_corto_job_id,
                    "subprocess_key": row.subprocess_key,
                    "output_payload": row.output_payload,
                }
            )
            payload = dict(row.output_payload or {})
            changed = False
            for key in ("audioPath", "speedFile", "finalMp3"):
                current = payload.get(key)
                updated = _translate_path(current)
                if current != updated:
                    payload[key] = updated
                    counters["changes"] += 1
                    changed = True
                    if len(sample_changes) < 20:
                        sample_changes.append(
                            {
                                "table": "proceso2_corto_subprocess_states",
                                "id": row.id,
                                "field": f"output_payload.{key}",
                                "old": current,
                                "new": updated,
                            }
                        )
            if changed:
                row.output_payload = payload

        backups["proceso4_subprocess_states"] = []
        for row in Proceso4SubprocessState.query.all():
            backups["proceso4_subprocess_states"].append(
                {
                    "id": row.id,
                    "proceso1_job_id": row.proceso1_job_id,
                    "subprocess_key": row.subprocess_key,
                    "output_payload": row.output_payload,
                }
            )
            payload = dict(row.output_payload or {})
            current = payload.get("videoPath")
            updated = _translate_path(current)
            if current != updated:
                payload["videoPath"] = updated
                row.output_payload = payload
                counters["changes"] += 1
                if len(sample_changes) < 20:
                    sample_changes.append(
                        {
                            "table": "proceso4_subprocess_states",
                            "id": row.id,
                            "field": "output_payload.videoPath",
                            "old": current,
                            "new": updated,
                        }
                    )

        backup_dir = _backup_dir()
        for table_name, rows in backups.items():
            _dump_backup(backup_dir / f"{table_name}.json", rows)

        report = {
            "mode": "apply" if args.apply else "dry-run",
            "backup_dir": str(backup_dir),
            "changes": counters["changes"],
            "sample_changes": sample_changes,
        }

        if args.apply:
            db.session.commit()
        else:
            db.session.rollback()

        print(json.dumps(report, indent=2, ensure_ascii=False))
        db.session.remove()


if __name__ == "__main__":
    main()
