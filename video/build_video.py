"""Cut the raw recording into narrated beats and stitch the final demo video.

Inputs: video/out/raw/*.webm, video/out/timeline.json, video/out/audio/<beat>.mp3 (+ durations.json).
Output: video/out/throughline-demo.mp4 (1920x1080, H.264 yuv420p, AAC 44.1 kHz).
Usage: uv run python video/build_video.py
"""
import json
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

FF = "/opt/homebrew/bin/ffmpeg"
FP = "/opt/homebrew/bin/ffprobe"
HERE = Path(__file__).parent
OUT = HERE / "out"
SEG = OUT / "segments"
AUDIO = OUT / "audio"
FPS = 30
LEAD = 0.25          # narration starts this long after the beat's first frame
TAIL = 0.6           # minimum silence after the narration before the next beat
THINK_KEEP = 1.5     # seconds of the "Checking the graph…" state kept at least
VENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-profile:v", "high", "-video_track_timescale", "30000"]
AENC = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:6])}...\n{r.stderr[-2000:]}")


def probe_duration(path):
    r = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def beat_ranges(events):
    """[(beat_id, [(start, end), ...])] with the agent wait shortened."""
    marks = [e for e in events if e["kind"] in ("beat", "end", "error")]
    out = []
    for i, m in enumerate(marks):
        if m["kind"] != "beat":
            continue
        start = m["t"]
        end = marks[i + 1]["t"] if i + 1 < len(marks) else start + 5
        out.append([m["id"], start, end])
    result = []
    for bid, start, end in out:
        waits_s = [e["t"] for e in events if e["kind"] == "agent_wait_start" and start <= e["t"] < end]
        waits_e = [e["t"] for e in events if e["kind"] == "agent_wait_end" and start <= e["t"] <= end]
        if waits_s and waits_e:
            # Keep the beginning up to the first send, a little of the last (successful) wait, then the answer.
            ws, we = waits_s[-1], waits_e[-1]
            result.append((bid, [(start, ws), (ws, we), (we, end)]))
        else:
            result.append((bid, [(start, end)]))
    return result


def shorten_wait(ranges, narration):
    """For a 3-range beat (pre, wait, post) keep only as much of the wait as the narration needs."""
    if len(ranges) != 3:
        return ranges
    (a, ws), (_, we), (_, b) = ranges
    pre, post, wait = ws - a, b - we, we - ws
    need = narration + LEAD + TAIL - pre - post
    keep = max(THINK_KEEP, min(wait, need))
    return [(a, ws + keep), (we, b)]


def build_beat(raw, bid, ranges, out_path):
    mp3 = AUDIO / f"{bid}.mp3"
    narr = probe_duration(mp3)
    ranges = shorten_wait(ranges, narr)
    vlen = sum(b - a for a, b in ranges)
    total = max(vlen, narr + LEAD + TAIL)
    pad = total - vlen
    seek = max(0.0, ranges[0][0] - 1.0)
    span = ranges[-1][1] - seek + 1.0
    parts = []
    for i, (a, b) in enumerate((a - seek, b - seek) for a, b in ranges):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                     f"scale=1920:1080:flags=lanczos,setsar=1[v{i}]")
    vchain = ";".join(parts)
    labels = "".join(f"[v{i}]" for i in range(len(ranges)))
    vchain += f";{labels}concat=n={len(ranges)}:v=1:a=0[vc]"
    vchain += f";[vc]tpad=stop_mode=clone:stop_duration={pad:.3f},trim=duration={total:.3f},format=yuv420p[v]"
    ms = int(LEAD * 1000)
    achain = f"[1:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms},apad,atrim=duration={total:.3f}[a]"
    run([FF, "-v", "error", "-y", "-ss", f"{seek:.3f}", "-t", f"{span:.3f}", "-i", str(raw), "-i", str(mp3),
         "-filter_complex", f"{vchain};{achain}", "-map", "[v]", "-map", "[a]",
         *VENC, *AENC, "-t", f"{total:.3f}", str(out_path)])
    return {"id": bid, "ranges": [[round(a, 2), round(b, 2)] for a, b in ranges], "video": round(vlen, 2),
            "narration": round(narr, 2), "length": round(total, 2)}


CARD_CSS = """
  html, body { margin: 0; width: 1920px; height: 1080px; }
  body { display: flex; align-items: center; justify-content: center;
    background: radial-gradient(1200px 700px at 30% 20%, #23408f 0%, #0d1530 60%, #070b1a 100%);
    color: #fff; font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  .wrap { text-align: center; max-width: 1500px; }
  h1 { font-size: 120px; margin: 0 0 18px; letter-spacing: -2px; }
  .tag { font-size: 50px; font-weight: 500; color: #dfe7ff; margin: 0 0 56px; }
  .meta { font-size: 38px; color: #aebde8; margin: 10px 0; }
  .big { font-size: 62px; font-weight: 700; margin: 0 0 40px; }
  .line { font-size: 42px; color: #dfe7ff; margin: 16px 0; }
  .small { font-size: 32px; color: #9fb0dd; margin-top: 50px; }
  svg { width: 140px; height: 140px; margin-bottom: 26px; }
"""
LOGO = """<svg viewBox="0 0 40 40"><rect x="1" y="1" width="38" height="38" rx="10" fill="#2f5bd3"/>
<path d="M8 27 C 14 27, 14 13, 20 13 S 26 27, 32 27" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"/>
<circle cx="8" cy="27" r="3.2" fill="white"/><circle cx="20" cy="13" r="3.2" fill="white"/><circle cx="32" cy="27" r="3.2" fill="#ffc400"/></svg>"""
TITLE_HTML = f"""<div class="wrap">{LOGO}<h1>Throughline</h1>
<p class="tag">Know what to learn before each talk</p>
<p class="meta">Team git lost &nbsp;·&nbsp; GitHub Universe 2026 &nbsp;·&nbsp; FalkorDB track</p></div>"""
END_HTML = f"""<div class="wrap">{LOGO}<p class="big">Built on FalkorDB</p>
<p class="line">Data via Bright Data &nbsp;·&nbsp; Agent and extraction by OpenAI</p>
<p class="line">github.com/Akshay171124/throughline</p>
<p class="small">Narration is AI-generated; the footage is the live app, recorded as it ran.<br>
Only the agent's waiting time was shortened.</p></div>"""


def render_cards():
    cards = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for name, html in (("title", TITLE_HTML), ("end", END_HTML)):
            pg.set_content(f"<!doctype html><html><head><meta charset='utf-8'><style>{CARD_CSS}</style></head><body>{html}</body></html>")
            path = SEG / f"card_{name}.png"
            pg.screenshot(path=str(path))
            cards[name] = path
        b.close()
    return cards


def card_clip(png, seconds, out_path):
    run([FF, "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(png),
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-filter_complex", f"[0:v]scale=1920:1080,setsar=1,fade=t=in:st=0:d=0.4,fade=t=out:st={seconds - 0.4}:d=0.4,format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a", "-t", str(seconds), *VENC, *AENC, str(out_path)])


def main():
    SEG.mkdir(parents=True, exist_ok=True)
    raw = sorted((OUT / "raw").glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
    events = json.loads((OUT / "timeline.json").read_text())["events"]
    cards = render_cards()
    clips = [SEG / "00_title.mp4"]
    card_clip(cards["title"], 3, clips[0])
    report = []
    for bid, ranges in beat_ranges(events):
        path = SEG / f"{bid}.mp4"
        info = build_beat(raw, bid, ranges, path)
        report.append(info)
        print(info, flush=True)
        clips.append(path)
    end = SEG / "99_end.mp4"
    card_clip(cards["end"], 4, end)
    clips.append(end)
    lst = SEG / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = OUT / "throughline-demo.mp4"
    run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "copy",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *AENC,
         "-movflags", "+faststart", str(final)])
    dur = probe_duration(final)
    # beat start times in the final video
    t = 3.0
    for info in report:
        info["starts_at"] = round(t, 1)
        t += info["length"]
    (OUT / "build_report.json").write_text(json.dumps({"duration": dur, "beats": report}, indent=2))
    print(f"final: {final}  duration {dur:.1f} s ({int(dur // 60)}:{int(dur % 60):02d})")
    if not 180 <= dur <= 300:
        print("WARNING: duration outside 3:00-5:00")


if __name__ == "__main__":
    main()
