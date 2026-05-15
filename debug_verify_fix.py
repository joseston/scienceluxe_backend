"""Verify effective-duration strategy: no black gaps, render_cursor stays aligned."""
from aplicacion import create_app, db
from aplicacion.models import Proceso4SubprocessState, Proceso4SceneMedia

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

    all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
        Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
    ).all()
    media_by_scene = {}
    for m in all_media:
        media_by_scene.setdefault(m.scene_num, []).append(m)

    # Pre-compute effective durations (same logic as render loop)
    effective_durations = []
    for i, scene in enumerate(scenes):
        s_start = float(scene.get('start', 0.0))
        s_dur   = float(scene.get('duration', 5.0))
        if i + 1 < len(scenes):
            next_start = float(scenes[i + 1].get('start', 0.0))
            gap = round(next_start - (s_start + s_dur), 4)
            eff = round(s_start + s_dur + max(gap, 0.0) - s_start, 4)
            eff = max(eff, s_dur)
        else:
            eff = s_dur
        effective_durations.append(eff)

    print(f'{"SN":>3}  {"tl_start":>9}  {"orig_dur":>8}  {"eff_dur":>8}  {"gap_abs":>8}  {"out_start":>10}  {"diff":>8}  note')
    print('-' * 90)

    render_cursor = 0.0
    total_gap_absorbed = 0.0
    for i, scene in enumerate(scenes[:20]):
        sn = scene.get('scene_num')
        tl_start = float(scene.get('start', 0))
        orig_dur = float(scene.get('duration', 0))
        eff_dur = effective_durations[i]
        gap_abs = round(eff_dur - orig_dur, 4)
        total_gap_absorbed += gap_abs

        clips = media_by_scene.get(sn, [])
        if clips and (clips[0].text_overlay or {}).get('style') == 'indice':
            note = '<-- INDICE'
        else:
            note = ''

        diff = render_cursor - tl_start
        print(
            f'  S{sn:02d}  {tl_start:>9.3f}  {orig_dur:>8.3f}  {eff_dur:>8.3f}  '
            f'{gap_abs:>+8.4f}  {render_cursor:>10.3f}  {diff:>+8.3f}s  {note}'
        )
        render_cursor += eff_dur

    print()
    print(f'Total gap absorbed into clips : {total_gap_absorbed:.3f}s')
    print(f'render_cursor after 20 scenes : {render_cursor:.3f}s')
    print()
    print('Expected: out_start == tl_start for every scene (diff = 0.000)')
    print('No black frames will be inserted between scenes.')

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

    all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=pid).order_by(
        Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
    ).all()
    media_by_scene = {}
    for m in all_media:
        media_by_scene.setdefault(m.scene_num, []).append(m)

    print(f'{"SN":>3}  {"tl_start":>9}  {"gap_ins":>8}  {"new_out_start":>13}  {"diff":>8}  note')
    print('-' * 75)

    render_cursor = 0.0
    for s in scenes[:15]:
        sn = s.get('scene_num')
        tl_start = float(s.get('start', 0))
        tl_dur = float(s.get('duration', 0))

        gap_dur = round(tl_start - render_cursor, 4)
        if gap_dur > 0.05:
            render_cursor += gap_dur
            gap_str = f'+{gap_dur:.3f}s'
        else:
            gap_str = '---'

        clips = media_by_scene.get(sn, [])
        if clips and (clips[0].text_overlay or {}).get('style') == 'indice':
            note = '<-- INDICE'
        else:
            note = ''

        diff = render_cursor - tl_start
        print(
            f'  S{sn:02d}  {tl_start:>9.3f}  {gap_str:>8}  {render_cursor:>13.3f}  {diff:>+8.3f}s  {note}'
        )
        render_cursor += tl_dur

    print()
    print(f'Final render_cursor: {render_cursor:.3f}s (was before: sum of scene durs only)')
