from pathlib import Path

def get_project_root() -> Path:
    """
    Resolve project root (where .env and backend/ reside).
    This utility is placed in backend/app/core/paths.py.
    """
    return Path(__file__).resolve().parents[3]
