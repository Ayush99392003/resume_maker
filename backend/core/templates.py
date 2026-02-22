import os
from pathlib import Path
from typing import Dict, List


class TemplateManager:
    """Manages LaTeX templates and placeholder substitution."""

    def __init__(self, templates_dir: str = "templates"):
        # Get the absolute path to the templates directory
        self.base_dir = Path(__file__).parent.parent / templates_dir
        self.templates: Dict[str, str] = {}
        self._load_templates()

    def _load_templates(self):
        """Loads all .tex files from the templates directory."""
        if not self.base_dir.exists():
            os.makedirs(self.base_dir, exist_ok=True)
            return

        for file in self.base_dir.glob("*.tex"):
            with open(file, "r", encoding="utf-8") as f:
                self.templates[file.stem] = f.read()

    def list_templates(self) -> List[str]:
        """Returns a list of available template names."""
        return list(self.templates.keys())

    def get_template(self, name: str) -> str:
        """Returns the raw content of a template by name."""
        return self.templates.get(name, "")

    def fill_template(self, name: str, data: Dict[str, str]) -> str:
        """
        Replaces placeholders in the format [[KEY]] with values from data.

        Args:
            name: Template name.
            data: Dictionary of placeholder keys and values.

        Returns:
            str: The LaTeX content with replaced values.
        """
        content = self.get_template(name)
        if not content:
            return ""

        for key, value in data.items():
            placeholder = f"[[{key.upper()}]]"
            content = content.replace(placeholder, str(value))

        return content


# Singleton instance
template_manager = TemplateManager()
