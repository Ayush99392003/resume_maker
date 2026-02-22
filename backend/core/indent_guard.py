import re
from typing import Dict, Tuple


class IndentGuard:
    """Validates and fixes LaTeX indentation and brace balance."""

    def check_brace_balance(self, latex: str) -> Tuple[bool, str]:
        """Checks if curly braces are balanced."""
        stack = []
        for i, char in enumerate(latex):
            if char == '{':
                stack.append(i)
            elif char == '}':
                if not stack:
                    return False, f"Unexpected closing brace at index {i}"
                stack.pop()

        if stack:
            return False, f"Unclosed brace at index {stack[-1]}"
        return True, "Balanced"

    def validate_indentation(self, latex: str) -> Dict[str, any]:
        """
        Validates indentation and basic syntax.

        Returns a health report.
        """
        balanced, msg = self.check_brace_balance(latex)

        # Check for \begin without matching \end (basic check)
        begins = len(re.findall(r'\\begin\{', latex))
        ends = len(re.findall(r'\\end\{', latex))

        env_balanced = (begins == ends)

        health_score = 100
        issues = []

        if not balanced:
            health_score -= 40
            issues.append(msg)

        if not env_balanced:
            health_score -= 40
            issues.append(
                f"Environment mismatch: {begins} begins vs {ends} ends")

        return {
            "is_healthy": health_score > 70,
            "score": health_score,
            "issues": issues
        }

    def format_latex(self, latex: str) -> str:
        """
        Simple auto-formatter for LaTeX indentation.
        """
        lines = latex.split('\n')
        formatted = []
        indent_level = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted.append("")
                continue

            # Decrease indent before printing if line starts with \end
            if stripped.startswith('\\end{'):
                indent_level = max(0, indent_level - 1)

            formatted.append("  " * indent_level + stripped)

            # Increase indent after printing if line contains \begin
            if stripped.startswith('\\begin{') and '\\end{' not in stripped:
                indent_level += 1

        return '\n'.join(formatted)


# Singleton
indent_guard = IndentGuard()
