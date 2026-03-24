from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlencode
from urllib.request import urlopen
import json

from daily_paper.collectors.base import BaseCollector
from daily_paper.models import Paper


class CrossrefCollector(BaseCollector):
    base_url = "https://api.crossref.org/works"

    def collect(
        self,
        keywords: list[str],
        start_date: datetime,
        max_results: int,
        journal_filters: list[str] | None = None,
    ) -> list[Paper]:
        en_keywords = [kw for kw in keywords if all(ord(c) < 128 for c in kw)]
        query = " ".join(en_keywords[:12])
        if journal_filters:
            query = f'{query} {" ".join(journal_filters[:4])}'
        params = {
            "query": query,
            "rows": str(max_results),
            "select": "DOI,title,container-title,published-print,published-online,is-referenced-by-count,author,URL,abstract,link",
            "filter": f"from-pub-date:{start_date.strftime('%Y-%m-%d')}",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        with urlopen(url, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        papers: list[Paper] = []
        for item in payload.get("message", {}).get("items", []):
            doi = (item.get("DOI") or "").strip().lower()
            if not doi:
                continue
            title = _strip_jats_tags(_first(item.get("title", [])))
            if not title:
                continue
            journal = _first(item.get("container-title", [])).lower()
            published = _parse_crossref_date(item)
            if not published:
                continue
            abstract = _strip_jats_tags((item.get("abstract") or "").strip())
            url = (item.get("URL") or "").strip()
            pdf_url = _extract_pdf_url(item.get("link", []))
            citations = _safe_int(item.get("is-referenced-by-count"))
            raw_authors = item.get("author", [])
            authors = _parse_authors(raw_authors)
            affiliations = _parse_affiliations(raw_authors)
            first_aff = _single_author_affiliation(raw_authors, 0)
            last_aff = _single_author_affiliation(raw_authors, -1)
            papers.append(
                Paper(
                    title=title,
                    abstract=abstract,
                    doi=doi,
                    journal=journal,
                    published_at=published,
                    url=url or f"https://doi.org/{doi}",
                    citations=citations,
                    source="crossref",
                    authors=authors,
                    affiliations=affiliations,
                    first_author_affiliation=first_aff,
                    last_author_affiliation=last_aff,
                    pdf_url=pdf_url,
                )
            )
        return papers


def _first(values: list[str]) -> str:
    if not values:
        return ""
    return str(values[0]).strip()


def _parse_crossref_date(item: dict) -> datetime | None:
    for field in ("published-print", "published-online", "issued"):
        parts = item.get(field, {}).get("date-parts", [])
        if not parts or not parts[0]:
            continue
        raw = parts[0]
        year = raw[0]
        month = raw[1] if len(raw) > 1 else 1
        day = raw[2] if len(raw) > 2 else 1
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _strip_jats_tags(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _parse_authors(raw_authors: list[dict]) -> list[str]:
    authors: list[str] = []
    for item in raw_authors:
        given = (item.get("given") or "").strip()
        family = (item.get("family") or "").strip()
        full = " ".join(part for part in (given, family) if part)
        if full:
            authors.append(full)
    return authors


def _extract_pdf_url(links: list[dict]) -> str:
    for item in links:
        content_type = (item.get("content-type") or "").lower()
        url = (item.get("URL") or "").strip()
        if not url:
            continue
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return url
    return ""


def _parse_affiliations(raw_authors: list[dict]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for author in raw_authors:
        for aff in author.get("affiliation", []):
            name = " ".join(str(aff.get("name", "")).split()).strip()
            if name and name not in seen:
                seen.add(name)
                values.append(name)
    return values


def _single_author_affiliation(raw_authors: list[dict], index: int) -> str:
    """Return the first affiliation name for the author at *index* (0=first, -1=last)."""
    if not raw_authors:
        return ""
    try:
        author = raw_authors[index]
    except IndexError:
        return ""
    affs = author.get("affiliation", [])
    if not affs:
        return ""
    return " ".join(str(affs[0].get("name", "")).split())

