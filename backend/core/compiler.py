import subprocess
import tempfile
from pathlib import Path


class CompilationError(Exception):
    """Exception raised when Tectonic compilation fails."""

    def __init__(self, message: str, logs: str):
        self.message = message
        self.logs = logs
        super().__init__(self.message)


class TectonicCompiler:
    """Wrapper for the Tectonic LaTeX engine."""

    def __init__(self, tectonic_path: str = "tectonic"):
        self.tectonic_path = tectonic_path

    def compile(self, latex_code: str) -> bytes:
        """
        Compiles LaTeX string into PDF bytes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tex_file = tmp_path / "resume.tex"

            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(latex_code)

            try:
                subprocess.run(
                    [
                        self.tectonic_path,
                        "--noninteractive",
                        "--chatter", "minimal",
                        str(tex_file)
                    ],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30  # Safety timeout
                )
            except subprocess.TimeoutExpired:
                raise CompilationError("Timeout", logs="Tectonic timed out.")
            except subprocess.CalledProcessError as e:
                logs = e.stdout + "\n" + e.stderr
                raise CompilationError("Tectonic failed", logs=logs)
            except FileNotFoundError:
                raise Exception("Tectonic not found.")

            pdf_file = tmp_path / "resume.pdf"
            if not pdf_file.exists():
                raise CompilationError("No PDF.", logs="No PDF found.")

            with open(pdf_file, "rb") as f:
                return f.read()


compiler = TectonicCompiler()
