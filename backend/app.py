from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ValidationError, field_validator

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import ffmpeg as bundled_ffmpeg
except ImportError:
    bundled_ffmpeg = None

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None
if Image is not None:
    Image.MAX_IMAGE_PIXELS = 40_000_000

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="openConvert API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"], allow_methods=["GET", "POST"], allow_headers=["*"])
MAX_UPLOAD = 150 * 1024 * 1024
MAX_MEDIA_OUTPUT = 512 * 1024 * 1024
MAX_DURATION = 2 * 60 * 60
def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if bundled_ffmpeg is not None and name in {"ffmpeg", "ffprobe"}:
        binary_attribute = {"ffmpeg": "FFMPEG_PATH", "ffprobe": "FFPROBE_PATH"}[name]
        bundled_path = getattr(bundled_ffmpeg, binary_attribute, None)
        if bundled_path and Path(bundled_path).is_file():
            return str(bundled_path)
    if os.name == "nt":
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        for path in packages.glob(f"Gyan.FFmpeg.Shared*/*/bin/{name}.exe"):
            return str(path)
    return None


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")
SOFFICE = shutil.which("soffice") or (r"C:\Program Files\LibreOffice\program\soffice.exe" if Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() else None)
GHOSTSCRIPT = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")

IMAGE_OUTPUTS = {"avif": "AVIF", "blp": "BLP", "bmp": "BMP", "dds": "DDS", "dib": "DIB", "eps": "EPS", "gif": "GIF", "ico": "ICO", "jp2": "JPEG2000", "jpg": "JPEG", "pcx": "PCX", "png": "PNG", "ppm": "PPM", "qoi": "QOI", "sgi": "SGI", "tga": "TGA", "tif": "TIFF", "tiff": "TIFF", "webp": "WEBP", "xbm": "XBM"}
IMAGE_INPUTS = {"AVIF": ["avif"], "BLP": ["blp"], "BMP": ["bmp"], "DDS": ["dds"], "DIB": ["dib"], "EPS": ["eps"], "GIF": ["gif"], "ICO": ["ico"], "JPEG": ["jpg", "jpeg"], "JPEG2000": ["jp2", "j2k"], "PCX": ["pcx"], "PNG": ["png"], "PPM": ["ppm", "pgm", "pbm"], "QOI": ["qoi"], "SGI": ["sgi"], "TGA": ["tga"], "TIFF": ["tif", "tiff"], "WEBP": ["webp"], "XBM": ["xbm"]}
AUDIO_CODECS = {"mp3": ("libmp3lame", "mp3"), "m4a": ("aac", "ipod"), "aac": ("aac", "adts"), "wav": ("pcm_s16le", "wav"), "flac": ("flac", "flac"), "opus": ("libopus", "opus"), "ogg": ("libvorbis", "ogg"), "aiff": ("pcm_s16be", "aiff"), "wma": ("wmav2", "asf")}
AUDIO_DOWNLOAD_FORMATS = {"mp3": "mp3", "m4a": "m4a", "aac": "aac", "wav": "wav", "flac": "flac", "opus": "opus", "ogg": "vorbis"}
VIDEO_CONTAINERS = {"mp4": ("libx264", "aac"), "mkv": ("libx264", "aac"), "webm": ("libvpx-vp9", "libopus"), "avi": ("mpeg4", "libmp3lame"), "mov": ("libx264", "aac"), "m4v": ("libx264", "aac"), "ts": ("mpeg2video", "mp2"), "mpeg": ("mpeg2video", "mp2"), "ogv": ("libtheora", "libvorbis")}
DOCUMENT_GROUPS = [
    {"category": "documents", "label": "المستندات والنصوص", "inputs": ["doc", "docx", "odt", "rtf", "txt", "html"], "outputs": ["pdf", "docx", "odt", "rtf", "txt", "html"]},
    {"category": "presentations", "label": "العروض التقديمية", "inputs": ["ppt", "pptx", "odp"], "outputs": ["pdf", "pptx", "odp"]},
    {"category": "spreadsheets", "label": "جداول البيانات", "inputs": ["xls", "xlsx", "ods", "csv"], "outputs": ["pdf", "xlsx", "ods"]},
]


def has_command(*args: str) -> bool:
    return bool(FFMPEG and subprocess.run([FFMPEG, "-hide_banner", *args], capture_output=True, timeout=8).returncode == 0)


def codec_available(name: str) -> bool:
    if not FFMPEG:
        return False
    result = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=8)
    return bool(re.search(rf"\b{re.escape(name)}\b", result.stdout + result.stderr))


def capability_data() -> dict:
    img_outputs = []
    if Image is not None:
        Image.init()
        img_outputs = [ext for ext, fmt in IMAGE_OUTPUTS.items() if fmt in Image.SAVE and ext not in ("tif",)]
        img_inputs = sorted({ext for fmt, extensions in IMAGE_INPUTS.items() if fmt in Image.OPEN and (fmt != "EPS" or GHOSTSCRIPT) for ext in extensions})
    else:
        img_inputs = []
    audio = [ext for ext, (codec, _) in AUDIO_CODECS.items() if codec_available(codec)] if FFMPEG else []
    video = [ext for ext, (video_codec, audio_codec) in VIDEO_CONTAINERS.items() if codec_available(video_codec) and codec_available(audio_codec)] if FFMPEG else []
    return {
        "maxUploadBytes": MAX_UPLOAD,
        "conversions": [
            {"category": "images", "label": "الصور", "inputs": img_inputs, "outputs": img_outputs, "available": bool(img_outputs)},
            {"category": "audio", "label": "الصوت", "inputs": ["mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma", "aiff"], "outputs": audio, "available": bool(audio)},
            {"category": "video", "label": "الفيديو", "inputs": ["mp4", "mkv", "mov", "webm", "avi", "m4v", "mpeg", "mpg", "3gp", "ts", "ogv"], "outputs": video, "available": bool(video)},
            *[{**item, "outputs": item["outputs"] if SOFFICE else [], "available": bool(SOFFICE), "reason": None if SOFFICE else "LibreOffice غير مثبت"} for item in DOCUMENT_GROUPS],
        ],
        "mediaDownload": {"available": yt_dlp is not None and FFMPEG is not None, "extractor": "yt-dlp", "note": "يدعم المواقع التي يستطيع yt-dlp استخراجها، وقد يتغير الدعم حسب المنصة والرابط."},
    }


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": bool(FFMPEG), "ffprobe": bool(FFPROBE), "ytDlp": yt_dlp is not None}


@app.get("/api/capabilities")
def capabilities():
    return capability_data()


@app.get("/")
def home():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js")
def frontend_js():
    return FileResponse(ROOT / "app.js", media_type="text/javascript")


@app.get("/styles.css")
def frontend_css():
    return FileResponse(ROOT / "styles.css", media_type="text/css")


def ffprobe(path: Path) -> dict:
    if not FFPROBE:
        raise HTTPException(503, "أداة فحص الوسائط ffprobe غير متاحة")
    try:
        result = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, "استغرق فحص الملف وقتًا أطول من المسموح")
    if result.returncode:
        raise HTTPException(415, "الملف تالف أو نوعه غير مدعوم")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(415, "تعذر قراءة معلومات الملف")


def image_open(path: Path):
    if Image is None:
        return None
    try:
        Image.init()
        with Image.open(path) as image:
            image.verify()
        image = Image.open(path)
        return ImageOps.exif_transpose(image)
    except Exception:
        return None


def safe_stem(filename: str | None) -> str:
    stem = Path(filename or "file").stem
    stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip(" .")
    return (stem[:100] or "file")


def cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def media_signature_ok(path: Path, ext: str) -> bool:
    with path.open("rb") as source:
        head = source.read(4096)
    if ext in {"mp4", "m4v", "m4a", "mov", "3gp", "3g2"}:
        return len(head) >= 8 and head[4:8] == b"ftyp"
    if ext in {"mkv", "webm"}:
        return head.startswith(bytes.fromhex("1A45DFA3"))
    if ext == "avi":
        return head.startswith(b"RIFF") and head[8:12] == b"AVI "
    if ext == "wav":
        return head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    if ext == "aiff":
        return head.startswith(b"FORM") and head[8:12] in (b"AIFF", b"AIFC")
    if ext in {"ogg", "opus", "ogv"}:
        return head.startswith(b"OggS")
    if ext == "flac":
        return head.startswith(b"fLaC")
    if ext == "mp3":
        return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if ext == "aac":
        return len(head) > 1 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0
    if ext == "wma":
        return head.startswith(bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C"))
    if ext in {"mpeg", "mpg"}:
        return head.startswith(b"\x00\x00\x01\xba") or head.startswith(b"\x00\x00\x01\xb3")
    if ext == "ts":
        return len(head) > 376 and head[0] == 0x47 and head[188] == 0x47 and head[376] == 0x47
    return False


@app.on_event("startup")
def cleanup_stale_workdirs() -> None:
    cutoff = time.time() - 24 * 60 * 60
    base = Path(tempfile.gettempdir())
    for pattern in ("openconvert-convert-*", "openconvert-media-*", "open-download-convert-*", "open-download-media-*"):
        for path in base.glob(pattern):
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    cleanup_dir(str(path))
            except OSError:
                continue


@app.post("/api/convert")
def convert_file(file: UploadFile = File(...), target: str = Form(...)):
    target = target.lower().lstrip(".")
    temp = tempfile.mkdtemp(prefix="openconvert-convert-")
    try:
        source = Path(temp) / ("input" + Path(file.filename or "file").suffix[:16])
        size = 0
        with source.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "حجم الملف يتجاوز 150 ميغابايت")
                out.write(chunk)
        image = image_open(source)
        output = Path(temp) / f"result.{target}"
        if image is not None:
            fmt = IMAGE_OUTPUTS.get(target)
            if not fmt or fmt not in Image.SAVE:
                raise HTTPException(415, "صيغة إخراج الصور هذه غير متاحة")
            if target in ("jpg", "jpeg"):
                if image.mode not in ("RGB", "L"):
                    background = Image.new("RGB", image.size, "white")
                    if "A" in image.getbands():
                        background.paste(image, mask=image.getchannel("A"))
                    else:
                        background.paste(image.convert("RGB"))
                    image = background
            elif target not in ("png", "webp", "tiff", "tif") and image.mode not in ("RGB", "L", "P"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            try:
                if fmt == "BLP":
                    image = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                elif fmt == "XBM":
                    image = image.convert("1")
                save_options = {"blp_version": "BLP2"} if fmt == "BLP" else ({"quality": 92} if fmt == "WEBP" else ({"quality": 90} if fmt in ("JPEG", "AVIF") else {}))
                image.save(output, format=fmt, **save_options)
            except Exception:
                raise HTTPException(422, "تعذر ترميز الصورة إلى الصيغة المطلوبة")
        elif SOFFICE and any(target in group["outputs"] for group in DOCUMENT_GROUPS):
            ext = Path(file.filename or "").suffix.lower().lstrip(".")
            allowed_documents = {ext for group in DOCUMENT_GROUPS for ext in group["inputs"]}
            if ext not in allowed_documents:
                raise HTTPException(415, "نوع المستند غير مدعوم")
            group = next(group for group in DOCUMENT_GROUPS if ext in group["inputs"])
            if target not in group["outputs"]:
                raise HTTPException(415, "صيغة الإخراج لا تناسب فئة المستند")
            head = source.read_bytes()[:16]
            signature_ok = (ext in {"docx", "odt", "pptx", "odp", "xlsx", "ods"} and zipfile.is_zipfile(source)) or (ext in {"doc", "ppt", "xls"} and head.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))) or (ext == "rtf" and head.startswith(b"{\\rtf")) or ext in {"txt", "html", "csv"}
            if not signature_ok:
                raise HTTPException(415, "محتوى الملف لا يطابق نوع المستند المعلن")
            if ext == target:
                raise HTTPException(422, "صيغة الملف هي نفسها صيغة الإخراج")
            profile = Path(temp) / "lo-profile"
            output_dir = Path(temp) / "converted"
            output_dir.mkdir()
            result = subprocess.run([SOFFICE, "--headless", "--nologo", "--nodefault", "--nolockcheck", f"-env:UserInstallation={profile.as_uri()}", "--convert-to", target, "--outdir", str(output_dir), str(source)], capture_output=True, text=True, timeout=180)
            candidates = [p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() == "." + target]
            if result.returncode or not candidates:
                raise HTTPException(422, "فشل تحويل المستند. قد لا تدعم LibreOffice هذا النوع من الملفات.")
            output = candidates[0]
        else:
            ext = Path(file.filename or "").suffix.lower().lstrip(".")
            media_inputs = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma", "aiff", "mp4", "mkv", "mov", "webm", "avi", "m4v", "mpeg", "mpg", "3gp", "3g2", "ts", "ogv"}
            if ext not in media_inputs or not media_signature_ok(source, ext):
                raise HTTPException(415, "محتوى الملف لا يطابق حاوية صوت أو فيديو مدعومة")
            inspected = ffprobe(source)
            streams = inspected.get("streams", [])
            duration = float(inspected.get("format", {}).get("duration") or 0)
            if duration > MAX_DURATION:
                raise HTTPException(413, "مدة الوسائط تتجاوز ساعتين")
            if target in AUDIO_CODECS and any(s.get("codec_type") == "audio" for s in streams):
                codec, muxer = AUDIO_CODECS[target]
                command = [FFMPEG, "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0", "-vn", "-c:a", codec, "-f", muxer, "-fs", str(MAX_MEDIA_OUTPUT), "-y", str(output)]
            elif target in VIDEO_CONTAINERS and any(s.get("codec_type") == "video" for s in streams):
                video_codec, audio_codec = VIDEO_CONTAINERS[target]
                command = [FFMPEG, "-nostdin", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-c:v", video_codec, "-c:a", audio_codec]
                if target == "mp4":
                    command += ["-movflags", "+faststart"]
                command += ["-fs", str(MAX_MEDIA_OUTPUT), "-y", str(output)]
            else:
                raise HTTPException(415, "صيغة الإخراج لا تناسب نوع الوسائط أو محركها غير متاح")
            try:
                converted = subprocess.run(command, capture_output=True, timeout=900)
            except subprocess.TimeoutExpired:
                raise HTTPException(422, "تجاوز التحويل الحد الزمني المسموح")
            if converted.returncode:
                raise HTTPException(422, "فشل التحويل. قد لا يكون الترميز متاحًا لهذا الملف.")
        if not output.is_file() or output.stat().st_size == 0:
            raise HTTPException(422, "لم ينتج المحول ملفًا صالحًا")
        document_outputs = {ext for group in DOCUMENT_GROUPS for ext in group["outputs"]}
        if FFMPEG and target not in IMAGE_OUTPUTS and target not in document_outputs:
            ffprobe(output)
        media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "flac": "audio/flac", "opus": "audio/opus", "mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm", "avi": "video/x-msvideo"}.get(target, "application/octet-stream")
        return FileResponse(output, media_type=media_type, filename=f"{safe_stem(file.filename)}.{target}", background=BackgroundTask(cleanup_dir, temp))
    except Exception:
        cleanup_dir(temp)
        raise


class LinkRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def valid_public_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("أدخل رابط HTTP أو HTTPS عامًّا")
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("الروابط المحلية غير مسموحة")
        try:
            addresses = {ipaddress.ip_address(item[4][0].split("%", 1)[0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except (OSError, ValueError):
            raise ValueError("تعذر العثور على المضيف")
        if not addresses or any(not ip.is_global for ip in addresses):
            raise ValueError("العناوين الخاصة أو المحلية غير مسموحة")
        return value


def media_options():
    if yt_dlp is None:
        raise HTTPException(503, "yt-dlp غير مثبت؛ تنزيل الوسائط غير متاح")
    return {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True, "noplaylist": True, "socket_timeout": 20, "extractor_retries": 1, "no_color": True, "ffmpeg_location": FFMPEG}


@app.post("/api/media/info")
def media_info(request: LinkRequest):
    if yt_dlp is None or not FFMPEG:
        raise HTTPException(503, "يلزم yt-dlp وFFmpeg لتفعيل تنزيل الوسائط")
    try:
        with yt_dlp.YoutubeDL(media_options()) as ydl:
            info = ydl.extract_info(request.url, download=False)
    except Exception:
        raise HTTPException(422, "تعذر استخراج معلومات الرابط. تحقق من الرابط أو جرّب لاحقًا.")
    if not info:
        raise HTTPException(422, "لم يُعثر على وسيط قابل للتنزيل في هذا الرابط")
    duration = info.get("duration")
    if duration and duration > MAX_DURATION:
        raise HTTPException(413, "مدة الوسائط تتجاوز الحد المسموح (ساعتان)")
    formats = info.get("formats") or []
    qualities = sorted({str(f.get("height")) + "p" for f in formats if f.get("height") and f.get("vcodec") != "none"}, key=lambda x: int(x[:-1]))
    return {"title": info.get("title") or "وسيط", "duration": duration, "extractor": info.get("extractor_key") or "موقع مدعوم", "qualities": qualities[-8:], "audioAvailable": any(f.get("acodec") != "none" for f in formats)}


@app.get("/api/media/platforms")
def media_platforms():
    if yt_dlp is None:
        raise HTTPException(503, "yt-dlp غير مثبت؛ قائمة المنصات غير متاحة")
    from yt_dlp.extractor import list_extractor_classes

    extractors = []
    for extractor in list_extractor_classes():
        if getattr(extractor, "IE_DESC", None) is False:
            continue
        try:
            description = extractor.description()
        except Exception:
            description = extractor.IE_NAME
        if description:
            description = re.sub(r"^\s*-\s*", "", description)
            description = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", description)
            description = re.sub(r"[*`_]", "", description)
            extractors.append(re.sub(r"\s+", " ", description).strip())
    return {"version": getattr(getattr(yt_dlp, "version", None), "__version__", "unknown"), "extractors": extractors}


@app.post("/api/media/download")
def media_download(url: str = Form(...), mode: str = Form("video"), quality: str = Form("best"), output_format: str = Form("mp4")):
    if yt_dlp is None or not FFMPEG:
        raise HTTPException(503, "يلزم yt-dlp وFFmpeg لتفعيل تنزيل الوسائط")
    try:
        request = LinkRequest(url=url)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"])
    if mode not in ("video", "audio"):
        raise HTTPException(422, "نوع التنزيل غير صالح")
    if mode == "video" and output_format not in ("mp4", "mkv", "webm"):
        raise HTTPException(422, "صيغة الفيديو غير مدعومة")
    if mode == "audio" and output_format not in AUDIO_DOWNLOAD_FORMATS:
        raise HTTPException(422, "صيغة الصوت غير مدعومة")
    if quality != "best" and (not re.fullmatch(r"\d{2,4}", quality) or int(quality) > 4320):
        raise HTTPException(422, "الجودة المختارة غير صالحة")
    temp = tempfile.mkdtemp(prefix="openconvert-media-")
    try:
        if mode == "audio":
            opts = {**media_options(), "skip_download": False, "format": "bestaudio/best", "outtmpl": str(Path(temp) / "%(title).120B.%(ext)s"), "max_filesize": MAX_MEDIA_OUTPUT, "progress_hooks": [lambda status: (_ for _ in ()).throw(yt_dlp.utils.DownloadError("download size limit")) if status.get("downloaded_bytes", 0) > MAX_MEDIA_OUTPUT else None], "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_DOWNLOAD_FORMATS[output_format], "preferredquality": "192"}], "overwrites": True}
        else:
            selector = "bestvideo+bestaudio/best" if quality == "best" else f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
            opts = {**media_options(), "skip_download": False, "format": selector, "outtmpl": str(Path(temp) / "%(title).120B.%(ext)s"), "max_filesize": MAX_MEDIA_OUTPUT, "progress_hooks": [lambda status: (_ for _ in ()).throw(yt_dlp.utils.DownloadError("download size limit")) if status.get("downloaded_bytes", 0) > MAX_MEDIA_OUTPUT else None], "merge_output_format": output_format, "overwrites": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([request.url])
        outputs = [p for p in Path(temp).iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not outputs:
            raise HTTPException(422, "لم يكتمل التنزيل أو لم ينتج ملف قابل للتنزيل")
        output = max(outputs, key=lambda p: p.stat().st_size)
        if output.stat().st_size <= 0 or output.stat().st_size > MAX_MEDIA_OUTPUT:
            raise HTTPException(413, "حجم الملف الناتج يتجاوز الحد المسموح")
        ffprobe(output)
        return FileResponse(output, filename=output.name, media_type="application/octet-stream", background=BackgroundTask(cleanup_dir, temp))
    except HTTPException:
        cleanup_dir(temp)
        raise
    except Exception:
        cleanup_dir(temp)
        raise HTTPException(422, "تعذر تنزيل الرابط أو تحويله. قد تكون المنصة حظرت الطلب أو غير مدعومة حاليًا.")
