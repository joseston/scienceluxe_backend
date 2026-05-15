"""Debug: probe actual file durations vs timeline durations and simulate render timing."""
import os, json, subprocess
from pathlib import Path
from aplicacion import create_app, db
from aplicacion.models import Proceso4SubprocessState, Proceso4SceneMedia

FFPROBE = r'C:\Users\JOSE\miniconda3\envs\newenv\Library\bin\ffprobe.exe'

def probe_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-print_format', 'json', '-show_format', path],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10
        )
        if r.returncode == 0:
            info = json.loads(r.stdout)
            return float(info.get('format', {}).get('duration', -1))
    except Exception as e:
        return f'ERROR:{e}'
    return -1

app = create_app()
with app.app_context():
    pid = 3

    imp = Proceso4SubprocessState.query.filter_by(
        proceso1_job_id=pid, subprocess_key='import_timeline'
    ).first()
    tl = (imp.output_payload or {}).get('timeline', {})
    scenes = tl.get('scenes', [])

    ai = Proceso4SubprocessState.query.filter_by(
        proceso1_job_id=pid, subprocess_key='auto_indice'
    ).first()
    ai_out = ai.output_payload if ai else {}
    indice_block_start = float(ai_out.get('start', 0))
    indice_block_total = float(ai_out.get('total_duration', 0))

    all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
        Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
    ).all()
    media_by_scene = {}
    for m in all_media:
        media_by_scene.setdefault(m.scene_num, []).append(m)

    print('=== RENDER SIMULATION: per-scene timing ===')
    print(f'{"SN":>3} {"TL_start":>9} {"TL_dur":>7} {"clips":>5} {"clip_type":>10} '
          f'{"file_dur":>8} {"scene_dur_used":>14} {"indice_offset":>13}')
    print('-' * 90)

    cumulative = 0.0
    for s in scenes[:15]:   # first 15 scenes
        sn = s.get('scene_num', 0)
        tl_start = float(s.get('start', 0))
        tl_dur = float(s.get('duration', 0))
        clips = media_by_scene.get(sn, [])

        if not clips:
            clip_type = 'BLACK'
            file_dur = 'N/A'
            scene_dur_used = tl_dur
        elif len(clips) == 1:
            c = clips[0]
            overlay = c.text_overlay or {}
            if overlay.get('style') == 'indice':
                clip_type = 'INDICE'
            elif c.media_type == 'image':
                clip_type = 'IMAGE'
            else:
                clip_type = 'VIDEO'
            file_dur = probe_duration(c.file_path)
            scene_dur_used = tl_dur
        else:
            clip_type = f'MULTI({len(clips)})'
            file_dur = probe_duration(clips[0].file_path)
            scene_dur_used = tl_dur

        indice_offset = ''
        if clip_type == 'INDICE':
            offset = tl_start - indice_block_start
            indice_offset = f'{offset:.3f}s'

        print(
            f'  S{sn:02d} {tl_start:>9.3f} {tl_dur:>7.3f} {len(clips):>5} '
            f'{clip_type:>10} {str(file_dur):>8} {scene_dur_used:>14.3f} {indice_offset:>13}'
        )
        cumulative += tl_dur

    print()
    print(f'INDICE block_start={indice_block_start}  total={indice_block_total}')
    print()

    # ── Simulate exact output timestamps (cumulative)
    print('=== CUMULATIVE OUTPUT TIMESTAMPS (first 15 scenes) ===')
    cum = 0.0
    for s in scenes[:15]:
        sn = s.get('scene_num', 0)
        tl_dur = float(s.get('duration', 0))
        tl_start = float(s.get('start', 0))
        clips = media_by_scene.get(sn, [])
        if clips and (clips[0].text_overlay or {}).get('style') == 'indice':
            tag = '<-- INDICE STARTS HERE'
        else:
            tag = ''
        print(f'  S{sn:02d} output_start={cum:7.3f}s  tl_start={tl_start:7.3f}s  diff={cum-tl_start:+.3f}s  {tag}')
        cum += tl_dur
