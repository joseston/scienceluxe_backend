"""
Debug script for Project 19: Verify render timing alignment.

Checks:
1. effective_duration calculation matches render_cursor == timeline_start for every scene
2. Per-scene clip coverage vs effective_duration (finds scenes where clip < eff_dur)
3. Transition overlap impact analysis
4. Post-render actual duration verification (if render artifacts exist)
"""
import json
import subprocess
from pathlib import Path
from aplicacion import create_app, db
from aplicacion.models import Proceso4SubprocessState, Proceso4SceneMedia

PID = 19


def _probe_duration(filepath: str) -> float | None:
    """Probe actual video duration using ffprobe."""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def main():
    app = create_app()
    with app.app_context():
        # Load timeline
        imp = Proceso4SubprocessState.query.filter_by(
            proceso1_job_id=PID, subprocess_key='import_timeline'
        ).first()
        if not imp:
            print(f'ERROR: No import_timeline state found for project {PID}')
            return
        tl = (imp.output_payload or {}).get('timeline', {})
        scenes = tl.get('scenes', [])
        print(f'Project {PID}: {len(scenes)} scenes in timeline')
        print()

        # Load auto_indice info
        ai = Proceso4SubprocessState.query.filter_by(
            proceso1_job_id=PID, subprocess_key='auto_indice'
        ).first()
        ai_out = ai.output_payload if ai else {}
        indice_block_start = float(ai_out.get('start', 0))

        # Load all media assignments
        all_media = Proceso4SceneMedia.query.filter_by(proceso1_job_id=PID).order_by(
            Proceso4SceneMedia.scene_num, Proceso4SceneMedia.clip_index
        ).all()
        media_by_scene = {}
        for m in all_media:
            media_by_scene.setdefault(m.scene_num, []).append(m)

        # Pre-compute effective durations (same logic as render)
        effective_durations = []
        for i, scene in enumerate(scenes):
            s_start = float(scene.get('start', 0.0))
            s_dur = float(scene.get('duration', 5.0))
            if i + 1 < len(scenes):
                next_start = float(scenes[i + 1].get('start', 0.0))
                gap = round(next_start - (s_start + s_dur), 4)
                eff = round(s_start + s_dur + max(gap, 0.0) - s_start, 4)
                eff = max(eff, s_dur)
            else:
                eff = s_dur
            effective_durations.append(eff)

        # ─── Section 1: Timeline alignment ───
        print('=' * 120)
        print('SECTION 1: Render cursor alignment (render_cursor vs timeline start)')
        print('=' * 120)
        header = (f'{"SN":>4}  {"section":>10}  {"tl_start":>9}  {"orig_dur":>8}  '
                  f'{"eff_dur":>8}  {"gap_abs":>8}  {"cursor":>10}  {"drift":>8}  '
                  f'{"clips":>5}  {"clip_cov":>8}  {"trans_ovl":>9}  note')
        print(header)
        print('-' * 120)

        render_cursor = 0.0
        total_gap_absorbed = 0.0
        drift_issues = []
        short_clip_issues = []

        for i, scene in enumerate(scenes):
            sn = scene.get('scene_num', 0)
            section = scene.get('section', '?')
            tl_start = float(scene.get('start', 0))
            orig_dur = float(scene.get('duration', 0))
            eff_dur = effective_durations[i]
            gap_abs = round(eff_dur - orig_dur, 4)
            total_gap_absorbed += gap_abs

            clips = media_by_scene.get(sn, [])
            n_clips = len(clips)

            # Calculate clip coverage
            clip_coverage = 0.0
            transition_overlap = 0.0
            for ci, clip in enumerate(clips):
                ts = clip.trim_start or 0.0
                te = clip.trim_end
                d = clip.duration
                if te is not None:
                    clip_coverage += max(0, te - ts)
                elif d is not None:
                    clip_coverage += max(0, d - ts)
                else:
                    clip_coverage += 5.0
                # Transition overlap
                if ci < n_clips - 1:
                    trans = clip.transition_type or 'cut'
                    if trans != 'cut':
                        transition_overlap += clip.transition_duration or 0.0

            effective_clip_cov = clip_coverage - transition_overlap

            # Notes
            notes = []
            if clips and (clips[0].text_overlay or {}).get('style') == 'indice':
                notes.append('INDICE')
            if gap_abs > 0.05:
                notes.append(f'GAP+{gap_abs:.1f}s')
            if effective_clip_cov > 0 and effective_clip_cov < eff_dur - 0.1:
                shortfall = eff_dur - effective_clip_cov
                notes.append(f'SHORT-{shortfall:.1f}s')
                short_clip_issues.append((sn, section, eff_dur, effective_clip_cov, shortfall))
            if effective_clip_cov > eff_dur + 0.1:
                notes.append('EXCEED')
            if n_clips == 0:
                notes.append('NO-MEDIA')
            if transition_overlap > 0:
                notes.append(f'TRANS-OVL={transition_overlap:.1f}s')

            diff = render_cursor - tl_start
            if abs(diff) > 0.001:
                drift_issues.append((sn, diff))

            print(
                f'  S{sn:02d}  {section:>10}  {tl_start:>9.3f}  {orig_dur:>8.3f}  '
                f'{eff_dur:>8.3f}  {gap_abs:>+8.4f}  {render_cursor:>10.3f}  {diff:>+8.4f}  '
                f'{n_clips:>5}  {effective_clip_cov:>8.2f}  {transition_overlap:>9.2f}  '
                f'{" | ".join(notes)}'
            )
            render_cursor += eff_dur

        # ─── Summary ───
        print()
        print('=' * 120)
        print('SUMMARY')
        print('=' * 120)
        print(f'  Total scenes            : {len(scenes)}')
        print(f'  Scenes with media       : {sum(1 for sn in [s.get("scene_num") for s in scenes] if sn in media_by_scene)}')
        print(f'  Total gap absorbed      : {total_gap_absorbed:.3f}s')
        print(f'  Final render cursor     : {render_cursor:.3f}s')
        print(f'  Last scene end          : {float(scenes[-1].get("start", 0)) + float(scenes[-1].get("duration", 0)):.3f}s')
        print()

        # ─── Section 2: Drift analysis ───
        if drift_issues:
            print(f'  DRIFT ISSUES ({len(drift_issues)}):')
            for sn, diff in drift_issues:
                print(f'    S{sn:02d}: drift = {diff:+.4f}s')
        else:
            print('  DRIFT: None — cursor stays perfectly aligned ✓')
        print()

        # ─── Section 3: Short clip issues ───
        if short_clip_issues:
            print(f'  SHORT CLIP ISSUES ({len(short_clip_issues)}) — clips shorter than effective scene duration:')
            print(f'    {"SN":>4}  {"section":>10}  {"eff_dur":>8}  {"clip_cov":>8}  {"shortfall":>9}')
            for sn, sec, eff, cov, short in short_clip_issues:
                print(f'    S{sn:02d}  {sec:>10}  {eff:>8.3f}  {cov:>8.3f}  {short:>9.3f}')
            total_short = sum(s[4] for s in short_clip_issues)
            print(f'    TOTAL potential drift from short clips: {total_short:.3f}s')
            print(f'    → With the freeze-frame padding fix, these are now padded automatically.')
        else:
            print('  SHORT CLIPS: None — all clips cover their effective duration ✓')
        print()

        # ─── Section 4: Check actual render artifacts ───
        render_work = Path(f'../data/proceso4/{PID}/output/render_work')
        if render_work.exists():
            print('SECTION 4: Post-render actual duration check (existing render artifacts)')
            print('-' * 80)
            total_actual = 0.0
            total_expected = 0.0
            worst_drift = 0.0
            for i, scene in enumerate(scenes[:20]):  # Check first 20
                sn = scene.get('scene_num', 0)
                eff = effective_durations[i]
                scene_file = render_work / f'scene_{sn}.mp4'
                if scene_file.exists():
                    actual = _probe_duration(str(scene_file))
                    if actual:
                        diff = actual - eff
                        total_actual += actual
                        total_expected += eff
                        if abs(diff) > abs(worst_drift):
                            worst_drift = diff
                        flag = ' ← MISMATCH' if abs(diff) > 0.05 else ''
                        print(f'  S{sn:02d}: expected={eff:.3f}s  actual={actual:.3f}s  diff={diff:+.4f}s{flag}')
            if total_expected > 0:
                cum_drift = total_actual - total_expected
                print(f'  Cumulative drift over {min(20, len(scenes))} scenes: {cum_drift:+.4f}s')
                print(f'  Worst single-scene drift: {worst_drift:+.4f}s')
                print(f'  Projected drift over {len(scenes)} scenes: {cum_drift * len(scenes) / min(20, len(scenes)):+.2f}s')
        else:
            print('SECTION 4: No render artifacts found (render not yet executed for this project)')

        print()
        print('Done.')


if __name__ == '__main__':
    main()
