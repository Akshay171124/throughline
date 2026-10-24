"""Stitch the demo video: slides and live-app footage, each with its narration.

Inputs: video/narration.json (beat order and type), video/out/slides/*.png (video/slides.py),
video/out/raw/*.webm + video/out/timeline.json (video/record_demo.py), video/out/audio/<beat>.mp3.
Output: video/out/throughline-demo.mp4 (1920x1080, H.264 yuv420p, AAC 44.1 kHz).
Usage: uv run python video/build_video.py
"""
import json
import subprocess
from pathlib import Path

FF = "/opt/homebrew/bin/ffmpeg"
FP = "/opt/homebrew/bin/ffprobe"
HERE = Path(__file__).parent
OUT = HERE / "out"
SEG = OUT / "segments"
AUDIO = OUT / "audio"
SLIDES = OUT / "slides"
FPS = 30
TEMPO = 1.07         # narration plays 7% faster (record_demo.py holds beats for the same length)
LEAD = 0.2           # narration starts this long after the beat's first frame
TAIL = 0.35          # minimum pause after the narration before the next beat
THINK_KEEP = 1.5     # seconds of the "Checking the graph…" state kept at least
VENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-profile:v", "high", "-video_track_timescale", "30000"]
AENC = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:8])}...\n{r.stderr[-2000:]}")


def probe_duration(path):
    r = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def footage_ranges(events, bid):
    start = next(e["t"] for e in events if e["kind"] == "beat" and e["id"] == bid)
    end = next(e["t"] for e in events if e["kind"] == "beat_end" and e["id"] == bid)
    ws = [e["t"] for e in events if e["kind"] == "agent_wait_start" and start <= e["t"] < end]
    we = [e["t"] for e in events if e["kind"] == "agent_wait_end" and start <= e["t"] <= end]
    if ws and we:
        return [(start, ws[-1]), (ws[-1], we[-1]), (we[-1], end)]
    return [(start, end)]


def clip_ranges(events, marks):
    a = next(e["t"] for e in events if e["kind"] == marks[0])
    b = next(e["t"] for e in events if e["kind"] == marks[1])
    return [(a, b)]


def shorten_wait(ranges, need):
    """For a (pre, wait, post) beat keep only as much of the wait as the narration needs."""
    if len(ranges) != 3:
        return ranges
    (a, ws), (_, we), (_, b) = ranges
    keep = max(THINK_KEEP, min(we - ws, need - (ws - a) - (b - we)))
    return [(a, ws + keep), (we, b)]


def audio_chain(total):
    ms = int(LEAD * 1000)
    return (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,atempo={TEMPO},adelay={ms}|{ms},"
            f"apad,atrim=duration={total:.3f}[a]")


def render_caption_png(b, path):
    """A transparent 1920x1080 PNG with the caption bar (same look as the in-app overlay), for clips reused later."""
    from playwright.sync_api import sync_playwright
    html = f"""<!doctype html><html><head><meta charset='utf-8'><style>
      html, body {{ margin: 0; width: 1920px; height: 1080px; background: transparent; }}
      #cap {{ position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); width: 1640px; box-sizing: border-box;
        padding: 18px 32px; border-radius: 16px; background: rgb(12,18,34); color: #fff;
        font: 600 31px/1.25 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; text-align: center;
        box-shadow: 0 6px 24px rgba(0,0,0,.35); }}
      .k {{ display: inline-block; font-size: 20px; letter-spacing: 2.5px; text-transform: uppercase; color: #9fb8ff;
        font-weight: 800; margin-right: 16px; vertical-align: 4px; }}
    </style></head><body><div id="cap"><span class="k">{b.get('kicker', '')}</span>{b.get('caption', '')}</div></body></html>"""
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        pg = br.new_page(viewport={"width": 1920, "height": 1080})
        pg.set_content(html)
        pg.screenshot(path=str(path), omit_background=True)
        br.close()


def build_footage(raw, bid, ranges, narr, out_path, min_seconds=0.0, overlay=None):
    need = narr / TEMPO + LEAD + TAIL
    ranges = shorten_wait(ranges, need)
    vlen = sum(b - a for a, b in ranges)
    total = max(vlen, need, min_seconds)
    seek = max(0.0, ranges[0][0] - 1.0)
    span = ranges[-1][1] - seek + 1.0
    parts = []
    for i, (a, b) in enumerate((a - seek, b - seek) for a, b in ranges):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                     f"scale=1920:1080:flags=lanczos,setsar=1[v{i}]")
    labels = "".join(f"[v{i}]" for i in range(len(ranges)))
    vchain = ";".join(parts) + f";{labels}concat=n={len(ranges)}:v=1:a=0[vc]"
    if overlay:
        vchain += ";[vc][2:v]overlay=0:0[vo]"
    vchain += f";[{'vo' if overlay else 'vc'}]tpad=stop_mode=clone:stop_duration={total - vlen:.3f},trim=duration={total:.3f},format=yuv420p[v]"
    extra = ["-i", str(overlay)] if overlay else []
    run([FF, "-v", "error", "-y", "-ss", f"{seek:.3f}", "-t", f"{span:.3f}", "-i", str(raw), "-i", str(AUDIO / f"{bid}.mp3"), *extra,
         "-filter_complex", f"{vchain};{audio_chain(total)}", "-map", "[v]", "-map", "[a]",
         *VENC, *AENC, "-t", f"{total:.3f}", str(out_path)])
    return {"ranges": [[round(a, 2), round(b, 2)] for a, b in ranges], "length": round(total, 2)}


def build_slide(png, bid, narr, out_path, min_seconds=0.0, fade_in=False, fade_out=False):
    total = max(narr / TEMPO + LEAD + TAIL, min_seconds)
    fades = ""
    if fade_in:
        fades += ",fade=t=in:st=0:d=0.5"
    if fade_out:
        fades += f",fade=t=out:st={total - 0.8:.3f}:d=0.8"
    run([FF, "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(png),
         "-i", str(AUDIO / f"{bid}.mp3"),
         "-filter_complex", f"[0:v]scale=1920:1080,setsar=1{fades},format=yuv420p[v];{audio_chain(total)}",
         "-map", "[v]", "-map", "[a]", *VENC, *AENC, "-t", f"{total:.3f}", str(out_path)])
    return {"length": round(total, 2)}


SECTION_OF = {"S1": "1 Intro & problem", "S2": "2 Solution", "S3": "3 Live demo", "D_": "3 Live demo",
              "S4": "4 FalkorDB", "S5": "5 Bright Data", "S6": "6 Close"}


def main():
    SEG.mkdir(parents=True, exist_ok=True)
    beats = json.loads((HERE / "narration.json").read_text())
    raw = sorted((OUT / "raw").glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
    events = json.loads((OUT / "timeline.json").read_text())["events"]
    clips, report = [], []
    for i, b in enumerate(beats):
        bid, kind = b["id"], b.get("type", "footage")
        narr = probe_duration(AUDIO / f"{bid}.mp3")
        path = SEG / f"{i:02d}_{bid}.mp4"
        mins = float(b.get("min_seconds", 0))
        if kind == "slide":
            info = build_slide(SLIDES / f"slide_{b['slide']}.png", bid, narr, path, mins,
                               fade_in=(i == 0), fade_out=(i == len(beats) - 1))
        elif kind == "clip":
            cap = SEG / f"cap_{bid}.png"
            render_caption_png(b, cap)
            info = build_footage(raw, bid, clip_ranges(events, b["marks"]), narr, path, mins, overlay=cap)
        else:
            info = build_footage(raw, bid, footage_ranges(events, bid), narr, path, mins)
        info.update(id=bid, type=kind, narration=round(narr / TEMPO, 2))
        report.append(info)
        print(info, flush=True)
        clips.append(path)
    lst = SEG / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = OUT / "throughline-demo.mp4"
    run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "copy",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *AENC, "-movflags", "+faststart", str(final)])
    dur = probe_duration(final)
    t = 0.0
    sections = {}
    for info in report:
        info["starts_at"] = round(t, 1)
        sec = SECTION_OF.get(info["id"][:2], "?")
        sections[sec] = round(sections.get(sec, 0) + info["length"], 1)
        t += info["length"]
    (OUT / "build_report.json").write_text(json.dumps({"duration": dur, "sections": sections, "beats": report}, indent=2))
    for sec, s in sections.items():
        print(f"{sec:20s} {s:6.1f} s  {100 * s / dur:4.1f}%")
    print(f"final: {final}  duration {dur:.1f} s ({int(dur // 60)}:{int(dur % 60):02d})")
    if not 180 <= dur < 300:
        print("WARNING: duration outside 3:00-5:00")


if __name__ == "__main__":
    main()
