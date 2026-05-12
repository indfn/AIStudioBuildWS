import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def project_root() -> Path:
    """
    Returns the repository root directory, allowing callers to build absolute paths 
    that do not rely on the current working directory.
    """
    env_root = os.getenv("CAMOUFOX_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "cookies").exists():
            return parent

    # Fallback to original behavior if marker directory is missing
    return current.parents[min(2, len(current.parents) - 1)]


def logs_dir() -> Path:
    """Root directory for storing log files and screenshots."""
    return project_root() / "logs"


def cookies_dir() -> Path:
    """Root directory for storing persistent Cookie JSON files."""
    return project_root() / "cookies"
