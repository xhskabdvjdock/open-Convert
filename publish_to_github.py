import base64
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


OWNER = "xhskabdvjdock"
REPO = "open-Convert"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
FILES = [
    ".gitignore",
    "README.md",
    "app.js",
    "backend/app.py",
    "index.html",
    "requirements.txt",
    "server.py",
    "styles.css",
    "tests/conversion_matrix.py",
    "tests/integration_smoke.py",
    "tests/media_platform_smoke.py",
]


def call(method, path, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "openConvert-publisher",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    token = getpass.getpass("GitHub token (hidden input): ").strip()
    if not token:
        print("No token provided; nothing uploaded.")
        return 2

    try:
        call("GET", "/user", token)
        repo = call("GET", f"/repos/{OWNER}/{REPO}", token)
        if not repo.get("permissions", {}).get("push", True):
            print("This GitHub account does not have push access to the target repository.")
            return 3

        branch = call("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/main", token)
        parent = branch["object"]["sha"]
        commit = call("GET", f"/repos/{OWNER}/{REPO}/git/commits/{parent}", token)
        base_tree = commit["tree"]["sha"]

        entries = []
        for filename in FILES:
            content = Path(filename).read_bytes()
            blob = call(
                "POST",
                f"/repos/{OWNER}/{REPO}/git/blobs",
                token,
                {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
            )
            entries.append({"path": filename, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        tree = call(
            "POST",
            f"/repos/{OWNER}/{REPO}/git/trees",
            token,
            {"base_tree": base_tree, "tree": entries},
        )
        new_commit = call(
            "POST",
            f"/repos/{OWNER}/{REPO}/git/commits",
            token,
            {"message": "Add openConvert application", "tree": tree["sha"], "parents": [parent]},
        )

        latest = call("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/main", token)
        if latest["object"]["sha"] != parent:
            print("The main branch changed during upload. No branch update was made; rerun after reviewing the new commit.")
            return 4

        call(
            "PATCH",
            f"/repos/{OWNER}/{REPO}/git/refs/heads/main",
            token,
            {"sha": new_commit["sha"], "force": False},
        )
        print(f"Uploaded {len(FILES)} project files to {OWNER}/{REPO}:main.")
        print(f"Commit: {new_commit['sha']}")
        return 0
    except urllib.error.HTTPError as error:
        print(f"GitHub returned HTTP {error.code}; no token or response body was displayed.")
        return 5
    except urllib.error.URLError:
        print("Could not reach GitHub; no token or response body was displayed.")
        return 6


if __name__ == "__main__":
    sys.exit(main())
