from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlencode
from urllib.request import urlopen
import json

from daily_paper.collectors.base import BaseCollector
from daily_paper.models import Paper


class EuropePmcCollector(BaseCollector):
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def collect(
        self,
        keywords: list[str],
        start_date: datetime,
        max_results: int,
        journal_filters: list[str] | None = None,
    ) -> list[Paper]:
        en_keywords = [kw for kw in keywords if all(ord(c) < 128 for c in kw)]
        query = " OR ".join(en_keywords) if en_keywords else " OR ".join(keywords)
        date_filter = start_date.strftime("%Y-%m-%d")
        journal_clause = ""
        if journal_filters:
            clauses = [f'JOURNAL:"{name}"' for name in journal_filters if name.strip()]
            if clauses:
                journal_clause = " AND (" + " OR ".join(clauses) + ")"
        params = {
            "query": f"({query}) AND FIRST_PDATE:[{date_filter} TO *]{journal_clause}",
            "format": "json",
            "pageSize": str(max_results),
            "resultType": "core",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        with urlopen(url, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        papers: list[Paper] = []
        results = payload.get("resultList", {}).get("result", [])
        for item in results:
            doi = (item.get("doi") or "").strip().lower()
            if not doi:
                continue
            published = _parse_europe_date(item.get("firstPublicationDate", ""))
            if not published:
                continue
            title = _clean_text(item.get("title") or "")
            if not title:
                continue
            abstract = _clean_text(item.get("abstractText") or "")
            journal_info = item.get("journalInfo") or {}
            journal_obj = journal_info.get("journal") or {}
            journal = (journal_obj.get("title") or "").strip().lower()
            pmcid = (item.get("pmcid") or "").strip()
            urls = _extract_fulltext_urls(item)
            main_url = urls[0] if urls else ""
            pdf_url = _pick_pdf_url(urls)
            citations = _safe_int(item.get("citedByCount"))
            authors = _split_authors(item.get("authorString", ""))
            affiliations = _split_affiliations(item.get("affiliation", ""))
            author_list = _parse_author_list(item.get("authorList", {}))
            first_aff = _author_affiliation(author_list, 0)
            last_aff = _author_affiliation(author_list, -1)
            papers.append(
                Paper(
                    title=title,
                    abstract=abstract,
                    doi=doi,
                    journal=journal,
                    published_at=published,
                    url=main_url or f"https://doi.org/{doi}",
                    citations=citations,
                    source="europe_pmc",
                    authors=authors,
                    affiliations=affiliations,
                    first_author_affiliation=first_aff,
                    last_author_affiliation=last_aff,
                    pmcid=pmcid,
                    pdf_url=pdf_url,
                )
            )
        return papers


def _parse_europe_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y":
                parsed = parsed.replace(month=1, day=1)
            if fmt == "%Y-%m":
                parsed = parsed.replace(day=1)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _split_authors(author_string: str) -> list[str]:
    if not author_string:
        return []
    return [part.strip() for part in author_string.split(",") if part.strip()]


def _split_affiliations(affiliation_text: str) -> list[str]:
    if not affiliation_text:
        return []
    values = [seg.strip() for seg in affiliation_text.split(";") if seg.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _clean_text(text: str) -> str:
    raw = unescape(text)
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(no_tags.split())


def _extract_fulltext_urls(item: dict) -> list[str]:
    full_text = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
    if isinstance(full_text, dict):
        full_text = [full_text]
    urls: list[str] = []
    for entry in full_text:
        url = (entry.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


def _pick_pdf_url(urls: list[str]) -> str:
    for url in urls:
        low = url.lower()
        if low.endswith(".pdf") or "pdf" in low:
            return url
    return ""


def _parse_author_list(author_list_raw: dict) -> list[dict]:
    """Return the list of author dicts from authorList.author (handles list or single dict)."""
    raw = author_list_raw.get("author", []) if isinstance(author_list_raw, dict) else []
    if isinstance(raw, dict):
        raw = [raw]
    return raw if isinstance(raw, list) else []


def _author_affiliation(author_list: list[dict], index: int) -> str:
    """Extract affiliation string for the author at *index* (0=first, -1=last)."""
    if not author_list:
        return ""
    try:
        author = author_list[index]
    except IndexError:
        return ""
    aff = author.get("affiliation") or ""
    if isinstance(aff, list):
        aff = "; ".join(str(a) for a in aff if a)
    return " ".join(str(aff).split())

