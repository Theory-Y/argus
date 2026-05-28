"""
core.render — turn a memo markdown file into PDF (and optionally DOCX).

Thin wrapper over the existing scripts/export_pdf.py pipeline (pandoc +
reference.dotx + headless Chromium). Runs from the repo root because the script
resolves output/theme/reference.dotx relative to the cwd.

Rendering requires pandoc + a Chromium-family browser at runtime. If they are
unavailable the subprocess raises CalledProcessError; callers (the job worker)
should catch it and fall back to delivering markdown only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXPORT_SCRIPT = _REPO_ROOT / "scripts" / "export_pdf.py"
_BUILD_DOTX_SCRIPT = _REPO_ROOT / "scripts" / "build_reference_dotx.py"
_REFERENCE_DOTX = _REPO_ROOT / "output" / "theme" / "reference.dotx"


def _ensure_reference_dotx() -> None:
    if _REFERENCE_DOTX.exists():
        return
    subprocess.run(
        [sys.executable, str(_BUILD_DOTX_SCRIPT)],
        cwd=str(_REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )


def render(md_path: str | Path, date: str | None = None) -> dict[str, str]:
    """Render ``md_path`` to PDF + DOCX via the .dotx pipeline.

    Returns a dict of produced artifacts, e.g. ``{"md": ..., "pdf": ..., "docx": ...}``.
    """
    md_path = Path(md_path)
    _ensure_reference_dotx()

    cmd = [sys.executable, str(_EXPORT_SCRIPT), str(md_path)]
    if date:
        cmd += ["--date", date]
    subprocess.run(cmd, cwd=str(_REPO_ROOT), check=True, capture_output=True, text=True)

    base = md_path.with_suffix("")
    artifacts = {"md": str(md_path), "pdf": str(base.with_suffix(".pdf"))}
    docx = base.with_suffix(".docx")
    if docx.exists():
        artifacts["docx"] = str(docx)
    return artifacts
