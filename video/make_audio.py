"""Narration audio: one OpenAI TTS mp3 per beat, durations in video/out/audio/durations.json."""
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import throughline.config  # noqa: F401,E402  (loads .env)
from openai import OpenAI  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out" / "audio"
OUT.mkdir(parents=True, exist_ok=True)


def duration(path: Path) -> float:
    r = subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main(force: bool) -> None:
    beats = json.loads((HERE / "narration.json").read_text())
    client = OpenAI()
    durs = {}
    for b in beats:
        mp3 = OUT / f"{b['id']}.mp3"
        if force or not mp3.exists():
            res = client.audio.speech.create(
                model="gpt-4o-mini-tts", voice="coral", input=b["voiceover"],
                instructions="Clear, warm, confident product demo narrator; moderate pace.",
                response_format="mp3")
            mp3.write_bytes(res.content)
        durs[b["id"]] = round(duration(mp3), 3)
        print(b["id"], durs[b["id"]], flush=True)
    (OUT / "durations.json").write_text(json.dumps(durs, indent=2))
    print("total", round(sum(durs.values()), 1))


if __name__ == "__main__":
    main("--force" in sys.argv)
