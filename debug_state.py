"""Debug script: print full render-relevant state for project 3."""
import os, json
from aplicacion import create_app, db
from aplicacion.models import Proceso4SubprocessState, Proceso4SceneMedia, Proceso4AudioTrack

app = create_app()
with app.app_context():
    pid = 3

    # ── 1. Timeline scenes 6-12
    imp = Proceso4SubprocessState.query.filter_by(
        proceso1_job_id=pid, subprocess_key='import_timeline'
    ).first()
    tl = (imp.output_payload or {}).get('timeline', {})
    scenes = tl.get('scenes', [])
    print('=== TIMELINE SCENES 6-12 ===')
    for s in scenes:
        sn = s.get('scene_num')
        if sn and 6 <= sn <= 12:
            print(
                f"  S{sn:02d} | section={s.get('section'):<8} "
                f"| start={s.get('start'):<7} | dur={s.get('duration'):<6} "
                f"| text={s.get('text','')[:60]}"
            )

    # ── 2. Scene media S7-S12
    print()
    print('=== SCENE MEDIA (S7-S12) ===')
    media = (
        Proceso4SceneMedia.query
        .filter_by(proceso1_job_id=pid)
        .filter(Proceso4SceneMedia.scene_num.in_([7, 8, 9, 10, 11, 12]))
        .order_by(Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index)
        .all()
    )
    for m in media:
        fsize = os.path.getsize(m.file_path) if os.path.exists(m.file_path) else -1
        print(
            f"  S{m.scene_num:02d} clip#{m.clip_index} "
            f"| type={m.media_type:<6} | media_dur={m.duration} "
            f"| trim={m.trim_start}-{m.trim_end} "
            f"| overlay={m.text_overlay} "
            f"| file_ok={fsize > 0} ({fsize} bytes) "
            f"| {m.original_filename}"
        )

    # ── 3. auto_indice state
    print()
    print('=== AUTO_INDICE STATE ===')
    ai = Proceso4SubprocessState.query.filter_by(
        proceso1_job_id=pid, subprocess_key='auto_indice'
    ).first()
    print(json.dumps(ai.output_payload if ai else {}, indent=2, ensure_ascii=False))

    # ── 4. Audio tracks
    print()
    print('=== AUDIO TRACKS ===')
    tracks = Proceso4AudioTrack.query.filter_by(proceso1_job_id=pid).all()
    for t in tracks:
        fsize = os.path.getsize(t.file_path) if os.path.exists(t.file_path) else -1
        print(
            f"  {t.track_type:<16} | start={t.start_time} | vol={t.volume} "
            f"| file_ok={fsize > 0} | {t.original_filename}"
        )

    # ── 5. Rendered work files (if any)
    from pathlib import Path
    work_dir = Path(f'../data/projects/{pid}') / 'output' / 'render_work'
    if work_dir.exists():
        print()
        print(f'=== RENDER WORK FILES ({work_dir}) ===')
        for f in sorted(work_dir.iterdir()):
            sz = f.stat().st_size
            print(f"  {f.name:<30} {sz:>10} bytes")
    else:
        print()
        print(f'[render_work dir not found: {work_dir}]')

    # ── 6. Timeline total duration vs narration
    print()
    print('=== TIMING SANITY CHECK ===')
    if scenes:
        last = scenes[-1]
        tl_end = float(last.get('start', 0)) + float(last.get('duration', 0))
        print(f"  Timeline last scene end  : {tl_end:.3f}s")
    ai_out = ai.output_payload if ai else {}
    ind_start = ai_out.get('start', 'N/A')
    ind_total = ai_out.get('total_duration', 'N/A')
    print(f"  INDICE block start       : {ind_start}")
    print(f"  INDICE block total_dur   : {ind_total}")
    if ind_start != 'N/A' and ind_total != 'N/A':
        print(f"  INDICE block end         : {float(ind_start) + float(ind_total):.3f}s")
