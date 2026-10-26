"""Launch the openConvert API and web application locally."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
from backend.app import app


if __name__ == "__main__":
    os.chdir(ROOT)
    if os.name == "nt":
        local_python = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        local_python = ROOT / ".venv" / "bin" / "python"
    python = str(local_python) if local_python.exists() else sys.executable
    if not (ROOT / "backend" / "app.py").is_file():
        raise SystemExit("Backend source is missing.")
    port = os.environ.get("PORT", "8000")
    raise SystemExit(subprocess.call([python, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", port]))
