from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from daily_paper.models import Paper


def score_paper(paper: Paper, config: dict[str, Any], all_keywords: list[str]) -> float:
    scoring_cfg = config["scoring"]
    journal_whitelist = config["journals"]["whitelist"]
    text_blob = f"{paper.title} {paper.abstract}".lower()

    keyword_hits = sum(1 for kw in all_keywords if kw.lower() in text_blob)
    keyword_score = keyword_hits * float(scoring_cfg["keyword_weight"])

    journal_score = float(_journal_score(paper.journal, journal_whitelist, config["journals"]["default_score"]))
    journal_score *= float(scoring_cfg.get("journal_weight_multiplier", 1))

    citation_bonus = min(
        float(paper.citations) * float(scoring_cfg["citation_weight"]),
        float(scoring_cfg["max_citation_bonus"]),
    )

    freshness_bonus = _freshness_bonus(paper.published_at, float(scoring_cfg["freshness_max_bonus"]))
    return keyword_score + journal_score + citation_bonus + freshness_bonus


def select_best_paper(
    papers: list[Paper],
    config: dict[str, Any],
    all_keywords: list[str],
    require_whitelist: bool = True,
) -> Paper | None:
    if not papers:
        return None

    journal_whitelist = config["journals"]["whitelist"]
    if require_whitelist:
        candidates = [paper for paper in papers if _is_journal_whitelisted(paper.journal, journal_whitelist)]
        if not candidates:
            return None
    else:
        candidates = papers
    scored = [(paper, score_paper(paper, config, all_keywords)) for paper in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[0][0]


def _freshness_bonus(published_at: datetime, max_bonus: float) -> float:
    now = datetime.now(timezone.utc)
    age_days = max((now - published_at).days, 0)
    if age_days >= 365:
        return 0
    return max_bonus * (1 - age_days / 365)


def _is_journal_whitelisted(journal: str, whitelist: dict[str, Any]) -> bool:
    name = _normalize_journal_name(journal)
    if not name:
        return False
    normalized_whitelist = {_normalize_journal_name(key) for key in whitelist}
    return name in normalized_whitelist


def _journal_score(journal: str, whitelist: dict[str, Any], default_score: float) -> float:
    name = _normalize_journal_name(journal)
    if not name:
        return float(default_score)
    for key, score in whitelist.items():
        key_l = _normalize_journal_name(key)
        if name == key_l:
            return float(score)
    return float(default_score)


def _normalize_journal_name(value: str) -> str:
    return " ".join(value.lower().strip().split())

