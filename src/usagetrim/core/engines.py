"""Select UsageTrim's own filter, or explicit pass-through."""

from usagetrim.core.companion_state import paused


def select_engine(requested: str) -> str:
    if requested not in {"auto", "usagetrim", "none"}:
        raise ValueError("engine must be auto, usagetrim, or none")
    return "none" if paused() or requested == "none" else "usagetrim"
