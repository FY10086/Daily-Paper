from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Paper:
    """Normalized paper object used across the pipeline."""

    title: str
    abstract: str
    doi: str
    journal: str
    published_at: datetime
    url: str
    citations: int = 0
    source: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    first_author_affiliation: str = ""
    last_author_affiliation: str = ""
    pmcid: str = ""
    pdf_url: str = ""
    fulltext_available: bool = False
    methods_excerpt: str = ""

