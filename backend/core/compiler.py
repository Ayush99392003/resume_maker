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
    from core.latex_compatibility import MAX_REPAIR_ATTEMPTS, RepairEngine
    from core.latex_soften import soften_latex_for_tectonic
    from core.logging_setup import get_logger
except ImportError:
    from . import config
    from .latex_compatibility import MAX_REPAIR_ATTEMPTS, RepairEngine
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
                    "-o",
                    str(outdir),
                    str(tex_file),
                ],
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
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

    def _soften_workspace_files(self, compile_dir: Path) -> None:
        """Soften all .cls and .sty files in compile_dir for Tectonic."""
        if not compile_dir.is_dir():
            return
        for pattern in ("*.cls", "*.sty"):
            for fpath in compile_dir.glob(pattern):
                try:
                    content = fpath.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    softened, notes = soften_latex_for_tectonic(content)
                    if notes:
                        fpath.write_text(softened, encoding="utf-8")
                        log.info(
                            "compiler: softened %s (%s)", fpath.name, notes
                        )
                except OSError as e:
                    log.warning(
                        "compiler: could not soften %s: %s", fpath.name, e
                    )

    def _seed_cls_files(self, compile_dir: Path) -> None:
        """Copy .cls and .sty files from backend/templates/ into compile_dir.

        This ensures custom document classes like resume.cls are always
        available to Tectonic regardless of whether a session workspace is
        used or a temp directory. Softens all .cls and .sty files in the
        workspace to neutralize crashy packages.
        """
        templates_dir = _backend_root() / "templates"
        if templates_dir.is_dir():
            for pattern in ("*.cls", "*.sty"):
                for template_file in templates_dir.glob(pattern):
                    dest = compile_dir / template_file.name
                    if not dest.exists():
                        try:
                            shutil.copy2(template_file, dest)
                            log.debug(
                                "seeded %s into %s",
                                template_file.name,
                                compile_dir,
                            )
                        except OSError as e:
                            log.warning(
                                "could not seed %s: %s",
                                template_file.name,
                                e,
                            )
        self._soften_workspace_files(compile_dir)

    def compile(self, latex_code: str, *, project_dir: str | None = None) -> bytes:
        """
        Compile LaTeX string into PDF bytes.

        If project_dir is set (session workspace or Overleaf import), write
        resume.tex into that directory and compile there so .cls/.sty/images
        resolve.  .cls files from backend/templates/ are always seeded into
        the compile directory so custom document classes work everywhere.
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

        def _compile_in_dir(target_dir: Path, init_code: str) -> tuple[bytes, str]:
            self._seed_cls_files(target_dir)
            self._soften_workspace_files(target_dir)
            engine = RepairEngine(self)
            curr = init_code
            tf = target_dir / "resume.tex"

            for att in range(MAX_REPAIR_ATTEMPTS):
                tf.write_text(curr, encoding="utf-8")
                try:
                    self._run_tectonic(tf, target_dir, target_dir)
                    pf = target_dir / "resume.pdf"
                    if not pf.exists():
                        raise CompilationError(
                            "No PDF.", logs="No PDF found in compile dir."
                        )
                    return pf.read_bytes(), curr
                except CompilationError as err:
                    new_c, act = engine.repair_source_and_workspace(
                        curr, err.logs or "", compile_dir=target_dir
                    )
                    if not act or att == MAX_REPAIR_ATTEMPTS - 1:
                        raise err
                    log.info(
                        "compile.auto_repair: attempt %s applied %s",
                        att + 1,
                        act,
                    )
                    curr = new_c

            raise CompilationError("Max repairs exceeded", logs="")

        if project_dir:
            root = Path(project_dir)
            if not root.is_dir():
                log.error("compile.error: project dir missing %s", project_dir)
                raise CompilationError(
                    "Project dir missing",
                    logs=f"No project directory: {project_dir}",
                )
            pdf_bytes, _ = _compile_in_dir(root, code)
            log.info("compile.step: ok project pdf_bytes=%s", len(pdf_bytes))
            return pdf_bytes

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_bytes, final_code = _compile_in_dir(tmp_path, code)
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
