from __future__ import annotations

from pathlib import Path


class SentLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def load(self) -> set[str]:
        with self.path.open("r", encoding="utf-8") as f:
            return {line.strip().lower() for line in f if line.strip()}

    def contains(self, doi: str) -> bool:
        return doi.lower() in self.load()

    def append(self, doi: str) -> None:
        clean = doi.strip().lower()
        if not clean:
            return
        existing = self.load()
        if clean in existing:
            return
        with self.path.open("a", encoding="utf-8") as f:
            f.write(clean + "\n")

