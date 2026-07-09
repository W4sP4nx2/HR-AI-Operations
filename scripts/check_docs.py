"""Validate local Markdown links and publication hygiene."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {".aura", ".git", ".venv", "node_modules"}
LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
IDENTITY_PLACEHOLDERS = (
    "about the author",
    "github.com/<you>",
    "linkedin.com/in/<you>",
    "<your name>",
)


def markdown_files() -> list[Path]:
    return sorted(
        path for path in ROOT.rglob("*.md") if not any(part in IGNORED_PARTS for part in path.parts)
    )


def link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def main() -> int:
    errors: list[str] = []
    files = markdown_files()

    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)

        if path.parent == ROOT:
            lowered = text.lower()
            for placeholder in IDENTITY_PLACEHOLDERS:
                if placeholder in lowered:
                    errors.append(f"{relative}: remove identity placeholder {placeholder!r}")

        for match in LINK_RE.finditer(text):
            target = link_target(match.group(1))
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue

            local_part = unquote(target.split("#", 1)[0])
            if not local_part:
                continue
            destination = (path.parent / local_part).resolve()
            if not destination.exists():
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{relative}:{line}: missing local target {target!r}")

    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Documentation checks passed for {len(files)} Markdown files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
