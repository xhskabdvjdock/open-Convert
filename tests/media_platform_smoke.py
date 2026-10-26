"""Network-dependent check for an actual YouTube extraction and video download."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import FFPROBE

BASE = "http://127.0.0.1:8000"
URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"  # Blender Foundation's Big Buck Bunny film


def main():
    response = requests.post(f"{BASE}/api/media/info", json={"url": URL}, timeout=120)
    response.raise_for_status()
    details = response.json()
    assert details["extractor"].lower() == "youtube" and details["title"]
    print(f"PASS YouTube metadata: {details['title']}; available qualities: {', '.join(details['qualities'])}")

    response = requests.post(f"{BASE}/api/media/download", data={"url": URL, "mode": "video", "quality": "144", "output_format": "mp4"}, timeout=600)
    response.raise_for_status()
    assert response.content
    with tempfile.TemporaryDirectory(prefix="open-download-youtube-check-") as folder:
        output = Path(folder) / "sample.mp4"
        output.write_bytes(response.content)
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(output)], capture_output=True, text=True, check=True, timeout=60)
        assert '"codec_type": "video"' in probe.stdout
    print(f"PASS YouTube 144p download: {len(response.content)} bytes; video stream verified")


if __name__ == "__main__":
    main()
