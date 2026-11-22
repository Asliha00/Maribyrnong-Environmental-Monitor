"""
Run the backend (Uvicorn, :8000) and the frontend (Vite, :5173) together.

    make dev            # Linux / macOS / Git Bash with make
    python scripts/dev.py   # anywhere, including Windows without make

Open http://localhost:5173. Vite proxies /api to Uvicorn, so the browser sees
one origin, as on Vercel. Ctrl+C stops both.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if not (ROOT / ".env").exists():
        print("No .env found. Create one first:  python scripts/init_env.py")
        return 1
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found. Install Node.js (see frontend/package.json engines).")
        return 1

    backend = subprocess.Popen(  # noqa: S603 - fixed argument list, no user input
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--reload",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
    )
    frontend = subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend")  # noqa: S603
    processes = [backend, frontend]
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return max((p.returncode or 0) for p in processes) if os.name != "nt" else 0


if __name__ == "__main__":
    sys.exit(main())
