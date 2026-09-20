"""Select TokenCut's own filter, or explicit pass-through."""

from tokencut.core.companion_state import paused


def select_engine(requested: str) -> str:
    if requested not in {"auto", "tokencut", "none"}:
        raise ValueError("engine must be auto, tokencut, or none")
    return "none" if paused() or requested == "none" else "tokencut"
