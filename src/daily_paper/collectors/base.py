from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from daily_paper.models import Paper


class BaseCollector(ABC):
    @abstractmethod
    def collect(
        self,
        keywords: list[str],
        start_date: datetime,
        max_results: int,
        journal_filters: list[str] | None = None,
    ) -> list[Paper]:
        raise NotImplementedError

