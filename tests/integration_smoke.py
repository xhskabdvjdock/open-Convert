"""Real local conversion smoke checks for the running open-Download API."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import FFMPEG, FFPROBE

BASE = "http://127.0.0.1:8000"


def upload(path: Path, target: str):
    with path.open("rb") as stream:
        response = requests.post(f"{BASE}/api/convert", files={"file": (path.name, stream)}, data={"target": target}, timeout=240)
    if response.status_code != 200:
        raise AssertionError(f"{path.suffix} to {target} failed: {response.status_code} {response.text[:200]}")
    if not response.content:
        raise AssertionError(f"{path.suffix} to {target} returned an empty file")
    return response


def main():
    health = requests.get(f"{BASE}/api/health", timeout=10)
    health.raise_for_status()
    info = health.json()
    assert info["ok"] and info["ffmpeg"] and info["ffprobe"] and info["ytDlp"]
    with tempfile.TemporaryDirectory(prefix="open-download-test-") as folder:
        work = Path(folder)

        image_path = work / "tiny.png"
        Image.new("RGB", (13, 9), (21, 133, 70)).save(image_path)
        converted = upload(image_path, "webp")
        with Image.open(io.BytesIO(converted.content)) as result:
            assert result.format == "WEBP" and result.size == (13, 9)
        print("PASS image PNG -> WEBP; output decoded and dimensions verified")

        wav_path = work / "tone.wav"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-y", str(wav_path)], check=True, timeout=30)
        converted = upload(wav_path, "mp3")
        out_audio = work / "converted.mp3"
        out_audio.write_bytes(converted.content)
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_name,codec_type", "-of", "json", str(out_audio)], capture_output=True, text=True, check=True, timeout=30)
        assert '"codec_name": "mp3"' in probe.stdout and '"codec_type": "audio"' in probe.stdout
        print("PASS audio WAV -> MP3; output codec verified with ffprobe")

        video_path = work / "clip.mp4"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=12:duration=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", str(video_path)], check=True, timeout=60)
        converted = upload(video_path, "mkv")
        out_video = work / "converted.mkv"
        out_video.write_bytes(converted.content)
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(out_video)], capture_output=True, text=True, check=True, timeout=30)
        assert '"codec_type": "video"' in probe.stdout and '"codec_type": "audio"' in probe.stdout
        print("PASS video MP4 -> MKV; video and audio streams verified with ffprobe")

        rtf_path = work / "note.rtf"
        rtf_path.write_text(r"{\rtf1\ansi open-Download conversion check}", encoding="ascii")
        converted = upload(rtf_path, "pdf")
        assert converted.content.startswith(b"%PDF-")
        print("PASS document RTF -> PDF; PDF signature verified")

        invalid = requests.post(f"{BASE}/api/media/info", json={"url": "http://127.0.0.1:8000/"}, timeout=10)
        assert invalid.status_code == 422
        print("PASS local/private media URL rejected")

        bad = requests.post(f"{BASE}/api/media/info", json={"url": "not a URL"}, timeout=10)
        assert bad.status_code == 422
        print("PASS malformed media URL rejected")

        bad_image = requests.post(f"{BASE}/api/convert", files={"file": ("bad.png", b"not an image")}, data={"target": "webp"}, timeout=20)
        assert bad_image.status_code == 415
        print("PASS invalid image content rejected")

    print("All local integration smoke checks passed.")


if __name__ == "__main__":
    main()
