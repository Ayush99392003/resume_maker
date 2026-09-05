"""Tectonic LaTeX compiler wrapper."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from core import config
    from core.latex_soften import soften_latex_for_tectonic
    from core.logging_setup import get_logger
except ImportError:
    from . import config
    from .latex_soften import soften_latex_for_tectonic
    from .logging_setup import get_logger

log = get_logger("compiler")


class CompilationError(Exception):
    """Exception raised when Tectonic compilation fails."""

    def __init__(self, message: str, logs: str):
        self.message = message
        self.logs = logs
        super().__init__(self.message)


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _pdf_cache_dir() -> Path:
    """Return directory for cached compiled PDFs."""
    configured = getattr(config, "PDF_CACHE_DIR", "")
    if configured:
        p = Path(configured)
    else:
        p = _backend_root() / "data" / "cache" / "pdf"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_tectonic_path() -> str:
    """Prefer TECTONIC_PATH, then local backend/bin, then PATH."""
    env = os.getenv("TECTONIC_PATH")
    if env and Path(env).exists():
        return env

    local = _backend_root() / "bin" / "tectonic.exe"
    if local.exists():
        return str(local)

    local_unix = _backend_root() / "bin" / "tectonic"
    if local_unix.exists():
        return str(local_unix)

    found = shutil.which("tectonic")
    if found:
        return found

    return "tectonic"


def ensure_fontconfig_files() -> Path:
    """
    Install fonts.conf where Windows Fontconfig/Tectonic look for it:
    - backend/fonts/fonts.conf (canonical)
    - backend/bin/fonts/fonts.conf (next to tectonic.exe)
    Returns path to the canonical fonts.conf.
    """
    root = _backend_root()
    src = root / "fonts" / "fonts.conf"
    cache_dir = root / "data" / "fontconfig-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use absolute cache path inside conf for reliability
    conf_body = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>C:/Windows/Fonts</dir>
  <dir>C:/Windows/System32/Fonts</dir>
  <cachedir>{cache_dir.resolve().as_posix()}</cachedir>

  <match target="pattern">
    <test qual="any" name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Arial</string></edit>
  </match>
  <match target="pattern">
    <test qual="any" name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Times New Roman</string></edit>
  </match>
  <match target="pattern">
    <test qual="any" name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Consolas</string></edit>
  </match>
</fontconfig>
"""
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(conf_body, encoding="utf-8")

    # Fontconfig on Windows often resolves relative to the executable
    exe_fonts = root / "bin" / "fonts"
    exe_fonts.mkdir(parents=True, exist_ok=True)
    (exe_fonts / "fonts.conf").write_text(conf_body, encoding="utf-8")

    # Also etc/fonts layout some builds expect beside bin/
    etc_fonts = root / "bin" / ".." / "etc" / "fonts"
    # Prefer backend/etc/fonts
    etc_fonts = root / "etc" / "fonts"
    etc_fonts.mkdir(parents=True, exist_ok=True)
    (etc_fonts / "fonts.conf").write_text(conf_body, encoding="utf-8")

    return src.resolve()


def apply_fontconfig_env(env: dict | None = None) -> dict:
    """Set FONTCONFIG_* on a env dict (and process env)."""
    conf = ensure_fontconfig_files()
    # Forward slashes avoid Windows path quirks in fontconfig
    conf_posix = conf.as_posix()
    conf_dir = conf.parent.as_posix()

    target = env if env is not None else os.environ
    target["FONTCONFIG_FILE"] = conf_posix
    target["FONTCONFIG_PATH"] = conf_dir
    target["FC_CONFIG"] = conf_posix
    return target


def _fontconfig_env() -> dict:
    """Env for Tectonic subprocess with Fontconfig configured."""
    env = os.environ.copy()
    apply_fontconfig_env(env)
    return env


class TectonicCompiler:
    """Wrapper for the Tectonic LaTeX engine."""

    def __init__(self, tectonic_path: str | None = None):
        apply_fontconfig_env()  # process-wide for any child tools
        self.tectonic_path = tectonic_path or _resolve_tectonic_path()

    def _run_tectonic(self, tex_file: Path, outdir: Path, cwd: Path) -> str:
        env = _fontconfig_env()
        log.debug(
            "tectonic compile tex=%s outdir=%s fontconfig=%s",
            tex_file,
            outdir,
            env.get("FONTCONFIG_FILE"),
        )
        try:
            proc = subprocess.run(
                [
                    self.tectonic_path,
                    "-X",
                    "compile",
                    "--outdir",
                    str(outdir),
                    str(tex_file),
                ],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
                timeout=240,
                env=env,
            )
            logs = (proc.stdout or "") + "\n" + (proc.stderr or "")
            log.debug("tectonic ok chars_out=%s", len(logs))
            return logs
        except subprocess.TimeoutExpired:
            log.error("tectonic timeout tex=%s", tex_file)
            raise CompilationError("Timeout", logs="Tectonic timed out.")
        except subprocess.CalledProcessError as e:
            logs = (e.stdout or "") + "\n" + (e.stderr or "")
            if "Fontconfig" in logs and "FONTCONFIG_FILE" in env:
                logs += (
                    f"\n[resume_maker] FONTCONFIG_FILE={env.get('FONTCONFIG_FILE')} "
                    f"(exists={Path(env['FONTCONFIG_FILE']).exists()})"
                )
            log.error(
                "tectonic failed code=%s tex=%s\n%s",
                e.returncode,
                tex_file.name,
                logs[-1200:],
            )
            raise CompilationError("Tectonic failed", logs=logs)
        except FileNotFoundError:
            log.error(
                "tectonic missing path=%s", self.tectonic_path
            )
            raise CompilationError(
                "Tectonic not found",
                logs="Install it or place tectonic.exe in backend/bin/. "
                "See https://tectonic-typesetting.github.io/book/latest/installation/",
            )

    def compile(self, latex_code: str, *, project_dir: str | None = None) -> bytes:
        """
        Compile LaTeX string into PDF bytes.

        If project_dir is set (Overleaf import with assets), write resume.tex
        into that directory and compile there so .cls/.sty/images resolve.
        """
        code, _ = soften_latex_for_tectonic(latex_code or "")
        use_cache = (
            getattr(config, "PDF_CACHE_ENABLED", True) and not project_dir
        )
        cache_key = ""
        cache_file = None
        if use_cache:
            cache_key = hashlib.sha256(code.encode("utf-8")).hexdigest()
            cache_file = _pdf_cache_dir() / f"{cache_key}.pdf"
            if cache_file.exists():
                try:
                    pdf_data = cache_file.read_bytes()
                    if pdf_data:
                        log.info(
                            "compile.cache_hit sha=%s bytes=%s",
                            cache_key[:12],
                            len(pdf_data),
                        )
                        return pdf_data
                except (OSError, ValueError) as cache_err:
                    log.warning("compile.cache_read_error %s", cache_err)

        log.info(
            "compile.step: start chars=%s project_dir=%s",
            len(code),
            bool(project_dir),
        )
        if project_dir:
            root = Path(project_dir)
            if not root.is_dir():
                log.error("compile.error: project dir missing %s", project_dir)
                raise CompilationError(
                    "Project dir missing",
                    logs=f"No project directory: {project_dir}",
                )
            tex_file = root / "resume.tex"
            tex_file.write_text(code, encoding="utf-8")
            self._run_tectonic(tex_file, root, root)
            pdf_file = root / "resume.pdf"
            if not pdf_file.exists():
                log.error("compile.error: no PDF in project dir %s", root)
                raise CompilationError("No PDF.", logs="No PDF found in project dir.")
            log.info("compile.step: ok project pdf_bytes=%s", pdf_file.stat().st_size)
            return pdf_file.read_bytes()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tex_file = tmp_path / "resume.tex"
            tex_file.write_text(code, encoding="utf-8")
            self._run_tectonic(tex_file, tmp_path, tmp_path)
            pdf_file = tmp_path / "resume.pdf"
            if not pdf_file.exists():
                raise CompilationError("No PDF.", logs="No PDF found.")
            pdf_bytes = pdf_file.read_bytes()
            if use_cache and cache_file:
                try:
                    tmp_cache = cache_file.with_suffix(".tmp")
                    tmp_cache.write_bytes(pdf_bytes)
                    os.replace(tmp_cache, cache_file)
                    log.info(
                        "compile.cache_saved sha=%s bytes=%s",
                        cache_key[:12],
                        len(pdf_bytes),
                    )
                except (OSError, ValueError) as save_err:
                    log.warning("compile.cache_save_error %s", save_err)
            return pdf_bytes

    async def compile_async(
        self, latex_code: str, *, project_dir: str | None = None
    ) -> bytes:
        """Asynchronously compile LaTeX into PDF bytes without blocking."""
        return await asyncio.to_thread(
            self.compile, latex_code, project_dir=project_dir
        )


# Configure fonts as soon as this module loads

apply_fontconfig_env()
compiler = TectonicCompiler()
