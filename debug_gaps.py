"""Detect gaps between consecutive timeline scenes."""
from aplicacion import create_app, db
from aplicacion.models import Proceso4SubprocessState

app = create_app()
with app.app_context():
    imp = Proceso4SubprocessState.query.filter_by(
        proceso1_job_id=3, subprocess_key='import_timeline'
    ).first()
    tl = (imp.output_payload or {}).get('timeline', {})
    scenes = tl.get('scenes', [])

    print(f'{"SN":>3}  {"start":>8}  {"dur":>6}  {"expected_next":>14}  {"actual_next":>12}  {"gap":>8}')
    print('-' * 70)
    total_gap = 0.0
    gaps = []
    for i in range(len(scenes) - 1):
        s = scenes[i]
        nxt = scenes[i + 1]
        sn = s.get('scene_num')
        start = float(s.get('start', 0))
        dur = float(s.get('duration', 0))
        expected_next = round(start + dur, 4)
        actual_next = float(nxt.get('start', 0))
        gap = round(actual_next - expected_next, 4)
        total_gap += gap
        if abs(gap) > 0.01:
            g = f'{gap:+.4f}s  <-- GAP'
            gaps.append((sn, gap))
        else:
            g = f'{gap:+.4f}s'
        print(f'  S{sn:02d}  {start:>8.3f}  {dur:>6.3f}  {expected_next:>14.4f}  {actual_next:>12.3f}  {g}')

    print()
    print(f'Total gap (sum of all inter-scene silences): {total_gap:.4f}s')
    print(f'Scenes with gap > 0.01s: {len(gaps)}')
    print()
    print('Gap detail:')
    for sn, g in gaps:
        print(f'  After S{sn:02d}: {g:+.4f}s')
