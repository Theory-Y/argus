"""server.jobs.tasks — the memo pipeline run off the request path.

build_context (src engine) → write_memo (Anthropic, hidden prompt) → render
(pdf/docx) → storage. Failure to render is non-fatal: we still deliver markdown.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core import engine, render
from core.memo import writer

from ..config import get_settings
from ..db.models import Job, JobStatus
from ..db.session import SessionLocal
from ..storage import get_storage

logger = logging.getLogger(__name__)


def _set(db, job: Job, *, status=None, progress=None, error=None) -> None:
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if error is not None:
        job.error = error[:2048]
    db.commit()


def generate_memo(job_id: str) -> None:
    """Worker entry point. Runs the full pipeline and updates the Job row."""
    settings = get_settings()
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("generate_memo: job %s not found", job_id)
            return

        ticker = job.ticker.upper()
        _set(db, job, status=JobStatus.processing, progress=10)

        with tempfile.TemporaryDirectory(prefix=f"theoryy_{ticker}_") as work:
            work_dir = Path(work)
            context_json = engine.build_context(ticker, work_dir)
            _set(db, job, progress=40)

            memo_md = writer.write_memo(
                ticker,
                context_json,
                model=settings.anthropic_model,
                effort=settings.anthropic_effort,
                max_tokens=settings.anthropic_max_tokens,
            )
            md_path = work_dir / f"TheoryY_Memo_{ticker}.md"
            md_path.write_text(memo_md, encoding="utf-8")
            _set(db, job, progress=70)

            try:
                artifacts = render.render(md_path)
            except Exception as exc:  # pandoc/chromium unavailable → md-only fallback
                logger.warning("render failed for %s, delivering markdown only: %s", ticker, exc)
                artifacts = {"md": str(md_path)}

            keys = get_storage().save(job_id, artifacts)

        job.artifacts = keys
        job.completed_at = datetime.now(timezone.utc)
        _set(db, job, status=JobStatus.complete, progress=100)

    except Exception as exc:
        logger.exception("generate_memo failed for job %s", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            _set(db, job, status=JobStatus.failed, error=str(exc))
    finally:
        db.close()
