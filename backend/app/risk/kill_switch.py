from __future__ import annotations

from pathlib import Path


class KillSwitch:
    def __init__(self, path: Path) -> None:
        self.path = path

    def is_active(self) -> bool:
        return self.path.exists()

    def activate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("active", encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

