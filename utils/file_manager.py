"""utils/file_manager.py — Helpers for temp file handling and cleanup."""

import shutil
from pathlib import Path

from config import OUTPUT_DIR
from utils.logger import get_logger

log = get_logger(__name__)


def fresh_run_dir() -> Path:
    """Create a clean temp directory for one pipeline run."""
    run_dir = OUTPUT_DIR / "run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    log.debug(f"Run directory: {run_dir}")
    return run_dir


def cleanup(path: Path) -> None:
    """Remove a file or directory tree silently."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except Exception as exc:
        log.warning(f"Cleanup failed for {path}: {exc}")
