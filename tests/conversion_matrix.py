"""Exercise every dynamically advertised image/audio/video and writer output."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import FFMPEG, FFPROBE

BASE = "http://127.0.0.1:8000"


def convert(path: Path, target: str) -> bytes:
    with path.open("rb") as source:
        response = requests.post(f"{BASE}/api/convert", files={"file": (path.name, source)}, data={"target": target}, timeout=240)
    if response.status_code != 200 or not response.content:
        raise AssertionError(f"{path.suffix} -> {target}: {response.status_code} {response.text[:180]}")
    return response.content


def verify_media(data: bytes, suffix: str, directory: Path):
    result = directory / f"result.{suffix}"
    result.write_bytes(data)
    probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(result)], capture_output=True, text=True, check=True, timeout=45)
    return probe.stdout


def create_test_odp(path: Path):
    content = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" office:version="1.2"><office:automatic-styles><style:style style:name="dp1" style:family="drawing-page"/><style:style style:name="gr1" style:family="graphic"/></office:automatic-styles><office:body><office:presentation><draw:page draw:name="page1" draw:style-name="dp1" draw:master-page-name="Default"><draw:frame draw:style-name="gr1" draw:name="Title" presentation:class="title" svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="4cm"><draw:text-box><text:p>Conversion matrix</text:p></draw:text-box></draw:frame></draw:page></office:presentation></office:body></office:document-content>'''
    styles = '''<?xml version="1.0" encoding="UTF-8"?><office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.2"><office:styles/><office:automatic-styles><style:page-layout style:name="PM1"><style:page-layout-properties fo:page-width="28cm" fo:page-height="21cm" fo:margin="1cm"/></style:page-layout></office:automatic-styles><office:master-styles><style:master-page style:name="Default" style:page-layout-name="PM1"/></office:master-styles></office:document-styles>'''
    manifest = '''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.presentation", compress_type=zipfile.ZIP_STORED)
        archive.writestr("content.xml", content)
        archive.writestr("styles.xml", styles)
        archive.writestr("META-INF/manifest.xml", manifest)


def main():
    capabilities = requests.get(f"{BASE}/api/capabilities", timeout=20).json()
    outputs = {item["category"]: item["outputs"] for item in capabilities["conversions"]}
    with tempfile.TemporaryDirectory(prefix="open-download-matrix-") as folder:
        directory = Path(folder)
        image = directory / "tiny.png"
        Image.new("RGB", (64, 48), (17, 129, 83)).save(image)
        image_count = 0
        for ext in outputs["images"]:
            data = convert(image, ext)
            try:
                with Image.open(io.BytesIO(data)) as decoded:
                    decoded.load()
            except Exception:
                if ext != "eps" or not data.startswith(b"%!PS-Adobe"):
                    raise
            image_count += 1
        print(f"PASS {image_count} advertised image output formats decoded or signature-checked")

        wav = directory / "tone.wav"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.35", "-y", str(wav)], check=True, timeout=30)
        for ext in outputs["audio"]:
            data = convert(wav, ext)
            assert '"codec_type": "audio"' in verify_media(data, ext, directory)
        print(f"PASS {len(outputs['audio'])} advertised audio output formats decoded by ffprobe")

        mp4 = directory / "clip.mp4"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:size=96x64:rate=8:duration=0.35", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.35", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", str(mp4)], check=True, timeout=45)
        for ext in outputs["video"]:
            data = convert(mp4, ext)
            streams = verify_media(data, ext, directory)
            assert '"codec_type": "video"' in streams
        print(f"PASS {len(outputs['video'])} advertised video output formats decoded by ffprobe")

        rtf = directory / "note.rtf"
        rtf.write_text(r"{\rtf1\ansi conversion matrix}", encoding="ascii")
        doc_outputs = [ext for ext in outputs["documents"] if ext != "rtf"]
        for ext in doc_outputs:
            data = convert(rtf, ext)
            if ext == "pdf":
                assert data.startswith(b"%PDF-")
            elif ext in {"docx", "odt"}:
                assert data.startswith(b"PK")
            else:
                assert data.strip()
        print(f"PASS {len(doc_outputs)} advertised text document conversions returned nonempty output")

        csv = directory / "sheet.csv"
        csv.write_text("name,value\nexample,42\n", encoding="utf-8")
        for ext in outputs["spreadsheets"]:
            data = convert(csv, ext)
            if ext == "pdf":
                assert data.startswith(b"%PDF-")
            else:
                assert data.startswith(b"PK")
        print(f"PASS {len(outputs['spreadsheets'])} spreadsheet conversions returned valid outputs")

        odp = directory / "slides.odp"
        create_test_odp(odp)
        for ext in [value for value in outputs["presentations"] if value != "odp"]:
            data = convert(odp, ext)
            assert data.startswith(b"%PDF-") if ext == "pdf" else data.startswith(b"PK")
        print(f"PASS {len(outputs['presentations']) - 1} presentation conversions returned valid outputs")


if __name__ == "__main__":
    main()
