"""docs/EVAL.md is shared by several reports: each owns one marked section."""

import re
from pathlib import Path


def marks(name: str) -> tuple[str, str]:
    return f"<!-- {name}:start -->", f"<!-- {name}:end -->"


def section(text: str, name: str) -> str | None:
    start, end = marks(name)
    m = re.search(re.escape(start) + r".*?" + re.escape(end), text, re.DOTALL)
    return m.group(0) if m else None


def write_section(path: Path, name: str, body: str) -> None:
    """Replace (or append) this report's section, keeping everything else."""
    start, end = marks(name)
    block = f"{start}\n{body.rstrip()}\n{end}"
    text = path.read_text() if path.exists() else ""
    old = section(text, name)
    text = text.replace(old, block) if old else text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text)


def keep_sections(new: str, old_path: Path, names: list[str]) -> str:
    """`new` plus the other reports' sections from the file it replaces."""
    old = old_path.read_text() if old_path.exists() else ""
    kept = [s for s in (section(old, n) for n in names) if s]
    return "\n\n".join([new.rstrip(), *kept]) + "\n"
