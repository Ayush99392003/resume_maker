"""Tectonic LaTeX compiler wrapper."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class CompilationError(Exception):
    """Exception raised when Tectonic compilation fails."""

    def __init__(self, message: str, logs: str):
        self.message = message
        self.logs = logs
        super().__init__(self.message)


def _resolve_tectonic_path() -> str:
    """Prefer TECTONIC_PATH, then local backend/bin, then PATH."""
    env = os.getenv("TECTONIC_PATH")
    if env and Path(env).exists():
        return env

    local = Path(__file__).resolve().parent.parent / "bin" / "tectonic.exe"
    if local.exists():
        return str(local)

    local_unix = Path(__file__).resolve().parent.parent / "bin" / "tectonic"
    if local_unix.exists():
        return str(local_unix)

    found = shutil.which("tectonic")
    if found:
        return found

    return "tectonic"


class TectonicCompiler:
    """Wrapper for the Tectonic LaTeX engine."""

    def __init__(self, tectonic_path: str | None = None):
        self.tectonic_path = tectonic_path or _resolve_tectonic_path()

    def compile(self, latex_code: str) -> bytes:
        """Compiles LaTeX string into PDF bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tex_file = tmp_path / "resume.tex"

            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(latex_code)

            try:
                # Tectonic 0.16+: use V2 compile interface
                subprocess.run(
                    [
                        self.tectonic_path,
                        "-X",
                        "compile",
                        "--outdir",
                        str(tmp_path),
                        str(tex_file),
                    ],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                raise CompilationError("Timeout", logs="Tectonic timed out.")
            except subprocess.CalledProcessError as e:
                logs = (e.stdout or "") + "\n" + (e.stderr or "")
                raise CompilationError("Tectonic failed", logs=logs)
            except FileNotFoundError:
                raise Exception(
                    "Tectonic not found. Install it or place tectonic.exe in "
                    "backend/bin/. See https://tectonic-typesetting.github.io/"
                    "book/latest/installation/"
                )

            pdf_file = tmp_path / "resume.pdf"
            if not pdf_file.exists():
                raise CompilationError("No PDF.", logs="No PDF found.")

            with open(pdf_file, "rb") as f:
                return f.read()


compiler = TectonicCompiler()
