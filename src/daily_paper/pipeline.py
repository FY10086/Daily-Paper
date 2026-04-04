from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from daily_paper.assets import enrich_open_access_assets, extract_figure_captions
from daily_paper.collectors import CrossrefCollector, EuropePmcCollector
from daily_paper.dedup import SentLog
from daily_paper.digest import build_digest_text
from daily_paper.digest.deepseek_client import build_digest_with_deepseek
from daily_paper.digest.openrouter_client import build_digest_with_openrouter
from daily_paper.mailer import send_email
from daily_paper.models import Paper
from daily_paper.ranker import select_best_paper


def run_pipeline(
    config: dict[str, Any],
    sent_log_path: str,
    smtp_config: dict[str, Any] | None = None,
    llm_config: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    keywords = _collect_keywords(config)
    max_results = int(config["sources"]["max_results_per_source"])
    time_cfg = config["time_window"]
    whitelist_journals = list(config["journals"]["whitelist"].keys())
    sent_log = SentLog(sent_log_path)
    sent_dois = sent_log.load()

    start_date = datetime.now(timezone.utc) - timedelta(days=int(time_cfg["primary_days"]))
    primary_candidates = _collect_all(config, keywords, start_date, max_results, whitelist_journals)
    primary_candidates = [paper for paper in primary_candidates if paper.doi not in sent_dois]
    papers = _enrich_and_filter_papers(primary_candidates, config)

    selection_mode = "scored"
    selected = select_best_paper(papers, config, keywords, require_whitelist=True)
    random_candidate_pool = list(primary_candidates)
    if not selected and bool(time_cfg.get("allow_fallback", True)):
        fallback_start = datetime.now(timezone.utc) - timedelta(days=int(time_cfg["fallback_days"]))
        fallback_candidates = _collect_all(config, keywords, fallback_start, max_results, whitelist_journals)
        fallback_candidates = [paper for paper in fallback_candidates if paper.doi not in sent_dois]
        random_candidate_pool = _merge_unique_papers(random_candidate_pool, fallback_candidates)
        fallback_papers = _enrich_and_filter_papers(fallback_candidates, config)
        selected = select_best_paper(fallback_papers, config, keywords, require_whitelist=True)
        if not selected and bool(config["journals"].get("allow_non_whitelist_fallback", True)):
            selected = select_best_paper(fallback_papers, config, keywords, require_whitelist=False)
    if not selected:
        selected = _select_random_medical_fallback(random_candidate_pool, config, sent_dois)
        if selected:
            selection_mode = "fallback_random"

    if not selected:
        return {"status": "empty", "message": "no paper selected"}

    selected = _enrich_assets_safe(selected)
    figure_captions = _extract_figures_safe(selected, int(config["interpretation"].get("max_figures", 6)))
    digest = _build_digest(selected, config, llm_config, figure_captions)
    subject = f"{config['delivery']['subject_prefix']} {selected.title[:90]}"
    recipients = config["delivery"]["recipients"]

    if not dry_run:
        if not smtp_config:
            raise ValueError("SMTP config is required when dry_run=False")
        send_email(
            host=smtp_config["host"],
            port=int(smtp_config["port"]),
            username=smtp_config["username"],
            password=smtp_config["password"],
            sender=smtp_config["sender"],
            recipients=recipients,
            subject=subject,
            body=digest,
        )
        sent_log.append(selected.doi)

    return {
        "status": "sent" if not dry_run else "dry_run",
        "selection_mode": selection_mode,
        "paper": _paper_to_summary(selected),
        "subject": subject,
        "recipients": recipients,
        "digest_preview": digest[:400],
        "figure_count": len(figure_captions),
        "fulltext_available": selected.fulltext_available,
    }


def _build_digest(
    selected: Paper,
    config: dict[str, Any],
    llm_config: dict[str, Any] | None,
    figure_captions: list[str],
) -> str:
    if llm_config and llm_config.get("api_key"):
        provider = (llm_config.get("provider") or "").lower()
        try:
            if provider == "openrouter":
                return build_digest_with_openrouter(selected, llm_config, figure_captions=figure_captions)
            if provider == "deepseek":
                return build_digest_with_deepseek(selected, llm_config, figure_captions=figure_captions)
        except Exception:
            # Keep daily job stable when LLM provider has rate/availability issues.
            return build_digest_text(selected, config, figure_captions=figure_captions)
    return build_digest_text(selected, config, figure_captions=figure_captions)


def _collect_all(
    config: dict[str, Any],
    keywords: list[str],
    start_date: datetime,
    max_results: int,
    whitelist_journals: list[str],
) -> list[Paper]:
    source_priority = config["sources"]["priority"]
    all_papers: list[Paper] = []
    for source in source_priority:
        if source == "europe_pmc":
            all_papers.extend(
                EuropePmcCollector().collect(
                    keywords,
                    start_date,
                    max_results,
                    journal_filters=whitelist_journals,
                )
            )
        elif source == "crossref":
            all_papers.extend(
                CrossrefCollector().collect(
                    keywords,
                    start_date,
                    max_results,
                    journal_filters=whitelist_journals,
                )
            )
    # deduplicate by DOI across collectors
    merged: dict[str, Paper] = {}
    for paper in all_papers:
        if paper.doi not in merged:
            merged[paper.doi] = paper
    return list(merged.values())


def _collect_keywords(config: dict[str, Any]) -> list[str]:
    return list(config["topic_keywords"]["en"])


def _merge_unique_papers(*paper_groups: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    for papers in paper_groups:
        for paper in papers:
            doi = paper.doi.strip().lower()
            if doi and doi not in merged:
                merged[doi] = paper
    return list(merged.values())


def _paper_to_summary(paper: Paper) -> dict[str, Any]:
    return {
        "title": paper.title,
        "doi": paper.doi,
        "journal": paper.journal,
        "published_at": paper.published_at.date().isoformat(),
        "url": paper.url,
        "source": paper.source,
        "pmcid": paper.pmcid,
        "fulltext_available": paper.fulltext_available,
    }


def _extract_figures_safe(selected: Paper, max_figures: int) -> list[str]:
    try:
        return extract_figure_captions(selected, max_figures=max_figures)
    except Exception:
        return []


def _enrich_assets_safe(selected: Paper) -> Paper:
    try:
        return enrich_open_access_assets(selected)
    except Exception:
        return selected


def _enrich_and_filter_papers(papers: list[Paper], config: dict[str, Any]) -> list[Paper]:
    content_cfg = config.get("content", {})
    require_full_text = bool(content_cfg.get("require_full_text", True))
    max_fulltext_checks = int(content_cfg.get("max_fulltext_checks", 12))
    papers = papers[:max_fulltext_checks]
    filtered: list[Paper] = []
    for paper in papers:
        enriched = _enrich_assets_safe(paper)
        if require_full_text and not enriched.fulltext_available:
            continue
        if not _is_target_research(enriched, content_cfg):
            continue
        filtered.append(enriched)
    return filtered


def _select_random_medical_fallback(
    papers: list[Paper],
    config: dict[str, Any],
    sent_dois: set[str],
) -> Paper | None:
    fallback_cfg = config.get("fallback_random", {})
    if not bool(fallback_cfg.get("enabled", False)):
        return None

    max_pool_size = max(int(fallback_cfg.get("pool_size", len(papers) or 1)), 1)
    journal_filters = [str(v).strip().lower() for v in fallback_cfg.get("journals", []) if str(v).strip()]
    medical_keywords = [
        str(v).strip().lower()
        for v in fallback_cfg.get("medical_include_any", _default_medical_keywords())
        if str(v).strip()
    ]

    candidates: list[Paper] = []
    seen: set[str] = set()
    for paper in papers:
        doi = paper.doi.strip().lower()
        if not doi or doi in sent_dois or doi in seen:
            continue
        seen.add(doi)
        if journal_filters and _normalize_text(paper.journal) not in journal_filters:
            continue
        if not _is_medical_related(paper, medical_keywords):
            continue
        candidates.append(paper)

    if not candidates:
        return None

    return random.choice(candidates[:max_pool_size])


def _is_medical_related(paper: Paper, medical_keywords: list[str]) -> bool:
    text_blob = _normalize_text(
        " ".join(
            [
                paper.title,
                paper.abstract,
                paper.journal,
                paper.first_author_affiliation,
                paper.last_author_affiliation,
                " ".join(paper.affiliations),
            ]
        )
    )
    return any(token in text_blob for token in medical_keywords)


def _default_medical_keywords() -> list[str]:
    return [
        "medical",
        "medicine",
        "clinical",
        "clinic",
        "patient",
        "patients",
        "hospital",
        "disease",
        "disorder",
        "syndrome",
        "cancer",
        "tumor",
        "tumour",
        "therapy",
        "treatment",
        "diagnosis",
        "diagnostic",
        "prognosis",
        "survival",
        "cohort",
        "mutation",
        "variant",
        "genetic",
        "genomic",
        "neurolog",
        "psychiatr",
        "cardi",
        "oncolog",
        "immun",
    ]


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _is_target_research(paper: Paper, content_cfg: dict[str, Any]) -> bool:
    text_blob = " ".join(
        [
            paper.title.lower(),
            paper.abstract.lower(),
            paper.methods_excerpt.lower(),
        ]
    )
    include_any = [str(v).lower() for v in content_cfg.get("include_any", [])]
    exclude_any = [str(v).lower() for v in content_cfg.get("exclude_any", [])]
    if include_any and not any(token in text_blob for token in include_any):
        return False
    # Use word-boundary matching to avoid excluding papers that merely *mention*
    # words like "reviewed" or "peer review process" in their abstracts.
    for token in exclude_any:
        if re.search(r"\b" + re.escape(token) + r"\b", text_blob):
            return False
    return True

