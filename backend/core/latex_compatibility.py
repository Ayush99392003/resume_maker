"""LaTeX compatibility, error classification, and targeted repair engine.

Provides automatic fallback chains for missing fonts (XeTeX/Tectonic fontspec),
undefined colors (xcolor), and missing side-files/packages from arbitrary
Overleaf templates without requiring destructive full-document LLM rewrites.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from core.logging_setup import get_logger
except ImportError:
    from .logging_setup import get_logger

log = get_logger("latex_compatibility")

# ---------------------------------------------------------------------------
# Handlers: Font Fallback Chain
# ---------------------------------------------------------------------------

SERIF_FALLBACK = "TeX Gyre Termes"
SANS_FALLBACK = "TeX Gyre Heros"
MONO_FALLBACK = "TeX Gyre Cursor"
DEFAULT_FALLBACK = "TeX Gyre Termes"

# Regexes to capture font declarations in .tex and .cls files
_FONT_CMD_RE = re.compile(
    r"(\\(?:setmainfont|setsansfont|setmonofont|newfontfamily|newfontface|fontspec)"
    r"(?:\s*\[[^\]]*\])?)\s*\{([^}]+)\}"
)

_FONTSPEC_ERR_RE = re.compile(
    r'(?:Package fontspec Error|fontspec error):\s*The font\s*["\']([^"\']+)["\']\s*cannot be found',
    re.IGNORECASE,
)

_XCOLOR_ERR_RE = re.compile(
    r"(?:Package xcolor Error:\s+)?Undefined color\s*[`']([^`']+)['`]",
    re.IGNORECASE,
)

_FILE_NOT_FOUND_RE = re.compile(
    r"(?:! LaTeX Error:\s+)?File\s*[`']([^`']+)['`]\s*not found",
    re.IGNORECASE,
)


def _classify_font_type(font_name: str, cmd_prefix: str = "") -> str:
    """Infer serif, sans, or mono from font name or command."""
    low_cmd = cmd_prefix.lower()
    low_name = font_name.lower()
    if "sans" in low_cmd or any(k in low_name for k in ("sans", "helvetica", "arial", "montserrat", "roboto", "lato")):
        return SANS_FALLBACK
    if "mono" in low_cmd or any(k in low_name for k in ("mono", "code", "courier", "fira", "consolas", "typewriter")):
        return MONO_FALLBACK
    return SERIF_FALLBACK


class FontHandler:
    """Resolves and substitutes unavailable fonts with standard TeX Gyre fonts."""

    @staticmethod
    def extract_missing_font(log_text: str) -> str | None:
        """Extract missing font name from Tectonic/fontspec error logs."""
        match = _FONTSPEC_ERR_RE.search(log_text)
        if match:
            return match.group(1).strip()
        # Fallback heuristic: font "XYZ" cannot be found
        alt = re.search(r'font\s+["\']([^"\']+)["\']\s+cannot be found', log_text, re.IGNORECASE)
        if alt:
            return alt.group(1).strip()
        return None

    @classmethod
    def repair_missing_font(
        cls,
        source: str,
        missing_font: str,
    ) -> tuple[str, dict[str, str] | None]:
        """Replace references to missing_font with an appropriate TeX Gyre fallback."""
        if not missing_font:
            return source, None

        escaped = re.escape(missing_font)
        # Base name without -Regular, -Bold, etc.
        base_name = re.sub(r"-(?:Regular|Bold|Italic|Light|Medium)", "", missing_font, flags=re.IGNORECASE)
        fallback = _classify_font_type(missing_font)

        replaced = False

        def _sub_font(m: re.Match) -> str:
            nonlocal replaced
            cmd_prefix = m.group(1)
            f_name = m.group(2).strip()
            if (
                f_name == missing_font
                or f_name == base_name
                or missing_font in f_name
                or base_name in f_name
            ):
                chosen_fallback = _classify_font_type(f_name, cmd_prefix)
                replaced = True
                return f"{cmd_prefix}{{{chosen_fallback}}}"
            return m.group(0)

        new_src = _FONT_CMD_RE.sub(_sub_font, source)

        if not replaced:
            # Try simple word boundary replacement inside braces: {missing_font}
            pat = re.compile(r"\{[ \t]*" + escaped + r"[ \t]*\}")
            if pat.search(new_src):
                new_src = pat.sub(f"{{{fallback}}}", new_src)
                replaced = True
            elif base_name != missing_font:
                pat_base = re.compile(r"\{[ \t]*" + re.escape(base_name) + r"[ \t]*\}")
                if pat_base.search(new_src):
                    new_src = pat_base.sub(f"{{{fallback}}}", new_src)
                    replaced = True

        if replaced:
            log.info("font_handler.repair: replaced %s with %s", missing_font, fallback)
            return new_src, {
                "type": "font",
                "original": missing_font,
                "replacement": fallback,
            }

        return new_src, None


# ---------------------------------------------------------------------------
# Handlers: Color Compatibility & Fallback
# ---------------------------------------------------------------------------

_KNOWN_COLORS = frozenset(
    [
        "black", "white", "red", "green", "blue", "cyan", "magenta", "yellow",
        "gray", "darkgray", "lightgray", "brown", "lime", "olive", "orange",
        "pink", "purple", "teal", "violet",
        # dvipsnames common
        "navyblue", "royalblue", "midnightblue", "cadetblue", "cornflowerblue",
        "darkorchid", "forestgreen", "goldenrod", "maroon", "periwinkle",
        "plum", "rawsienna", "rubinered", "salmon", "seagreen", "sepia",
        "tan", "thistle", "turquoise", "wildstrawberry",
    ]
)


class ColorHandler:
    """Detects missing colors and injects safe neutral or theme definitions."""

    @staticmethod
    def extract_missing_color(log_text: str) -> str | None:
        """Extract undefined color name from xcolor logs."""
        match = _XCOLOR_ERR_RE.search(log_text)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def define_missing_color(
        cls,
        source: str,
        color_name: str,
    ) -> tuple[str, dict[str, str] | None]:
        """Inject a fallback definition for the missing color into the preamble."""
        if not color_name:
            return source, None

        # Check if color is already defined to prevent duplicate clashes
        if re.search(r"\\(?:definecolor|providecolor)\{" + re.escape(color_name) + r"\}", source):
            return source, None

        # Infer fallback tone
        low = color_name.lower()
        if any(k in low for k in ("blue", "navy", "royal", "primary")):
            rgb = "37,99,235"  # Modern clean royal blue
        elif any(k in low for k in ("red", "ruby", "maroon", "danger")):
            rgb = "185,28,28"  # Professional brick red
        elif any(k in low for k in ("green", "forest", "emerald")):
            rgb = "22,101,52"  # Forest green
        elif any(k in low for k in ("gold", "yellow", "orange")):
            rgb = "217,119,6"  # Amber
        else:
            rgb = "75,85,99"   # Neutral dark slate grey

        def_stmt = f"\\providecolor{{{color_name}}}{{RGB}}{{{rgb}}}\n"

        # Insert right before \begin{document} or at the very top of preamble
        doc_match = re.search(r"\\begin\{document\}", source)
        if doc_match:
            idx = doc_match.start()
            new_src = source[:idx] + def_stmt + source[idx:]
        else:
            new_src = def_stmt + source

        log.info("color_handler.repair: defined missing color '%s' with RGB {%s}", color_name, rgb)
        return new_src, {
            "type": "color",
            "original": color_name,
            "action": f"defined fallback RGB {rgb}",
        }


# ---------------------------------------------------------------------------
# Handlers: File & Package Compatibility
# ---------------------------------------------------------------------------


class PackageHandler:
    """Handles missing side-files or missing packages in compile directory."""

    @staticmethod
    def extract_missing_file(log_text: str) -> str | None:
        """Extract missing filename from Tectonic error logs."""
        match = _FILE_NOT_FOUND_RE.search(log_text)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def repair_missing_file(
        cls,
        source: str,
        missing_file: str,
        compile_dir: Path | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        """Neutralize orphaned \\input{missing} references or touch dummy files."""
        if not missing_file:
            return source, None

        stem = Path(missing_file).stem
        ext = Path(missing_file).suffix

        # Pattern: \input{foo} or \input{foo.tex}
        pat = re.compile(
            r"^[ \t]*\\input\{[ \t]*"
            + re.escape(stem)
            + r"(?:\.tex)?[ \t]*\}[ \t]*%?.*$",
            re.MULTILINE,
        )
        repl_msg = f"% [auto-repair: removed missing \\input{{{missing_file}}}]"
        new_src, count = pat.subn(lambda _m: repl_msg, source)

        if count > 0:
            log.info("package_handler.repair: commented missing \\input{%s}", missing_file)
            return new_src, {
                "type": "package_or_file",
                "original": missing_file,
                "action": "commented missing \\input",
            }

        # If it's a side-file (.tex, .def, .cfg) in compile_dir, touch an empty file
        if compile_dir and compile_dir.is_dir() and ext in (".tex", ".def", ".cfg"):
            target_path = compile_dir / missing_file
            if not target_path.exists():
                try:
                    target_path.write_text("% Empty placeholder created by auto-repair\n", encoding="utf-8")
                    log.info("package_handler.repair: seeded empty placeholder for %s", missing_file)
                    return source, {
                        "type": "package_or_file",
                        "original": missing_file,
                        "action": "seeded empty dummy file",
                    }
                except OSError as err:
                    log.warning("could not write dummy file %s: %s", missing_file, err)

        return source, None


# ---------------------------------------------------------------------------
# Error Classifier
# ---------------------------------------------------------------------------


class ErrorClassifier:
    """Categorizes Tectonic logs into actionable repair categories."""

    @staticmethod
    def classify(log_text: str) -> str:
        """Return 'font', 'color', 'package_or_file', 'command', or 'unknown'."""
        if not log_text:
            return "unknown"

        if "fontspec Error" in log_text or "fontspec error" in log_text or "cannot be found" in log_text:
            return "font"

        if "Undefined color" in log_text or "Package xcolor Error" in log_text:
            return "color"

        if ("File `" in log_text or "File '" in log_text) and "not found" in log_text:
            return "package_or_file"

        if "Undefined control sequence" in log_text:
            return "command"

        return "unknown"


# ---------------------------------------------------------------------------
# Repair Engine Loop
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS = 5


class RepairEngine:
    """Coordinates targeted, deterministic auto-repair loops without LLM overhead."""

    def __init__(self, compiler_instance: Any):
        self.compiler = compiler_instance

    def repair_source_and_workspace(
        self,
        source: str,
        log_text: str,
        compile_dir: Path | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        """Inspect error logs and apply targeted deterministic repair to source and workspace."""
        category = ErrorClassifier.classify(log_text)

        # 1. Font Error
        if category == "font":
            missing_font = FontHandler.extract_missing_font(log_text)
            if missing_font:
                # Check if missing font is in .cls files in compile_dir
                if compile_dir and compile_dir.is_dir():
                    for cls_file in compile_dir.glob("*.cls"):
                        try:
                            cls_content = cls_file.read_text(encoding="utf-8", errors="replace")
                            new_cls, cls_action = FontHandler.repair_missing_font(cls_content, missing_font)
                            if cls_action:
                                cls_file.write_text(new_cls, encoding="utf-8")
                                log.info("repair_engine: repaired font '%s' in %s", missing_font, cls_file.name)
                                return source, cls_action
                        except (OSError, ValueError) as e:
                            log.warning("failed to check font in %s: %s", cls_file.name, e)

                # Check main .tex source
                new_src, action = FontHandler.repair_missing_font(source, missing_font)
                if action:
                    return new_src, action

        # 2. Color Error
        if category == "color":
            missing_color = ColorHandler.extract_missing_color(log_text)
            if missing_color:
                new_src, action = ColorHandler.define_missing_color(source, missing_color)
                if action:
                    return new_src, action

        # 3. Package or File Error
        if category == "package_or_file":
            missing_file = PackageHandler.extract_missing_file(log_text)
            if missing_file:
                new_src, action = PackageHandler.repair_missing_file(source, missing_file, compile_dir=compile_dir)
                if action:
                    return new_src, action

        return source, None
