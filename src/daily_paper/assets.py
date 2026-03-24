from __future__ import annotations

import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
import json

from daily_paper.models import Paper


def extract_figure_captions(paper: Paper, max_figures: int = 10) -> list[str]:
    captions = _extract_figures_from_epmc_xml(paper, max_figures=max_figures)
    if captions:
        return captions
    return _extract_figures_from_html(paper, max_figures=max_figures)


def enrich_open_access_assets(paper: Paper) -> Paper:
    if not paper.doi:
        return paper
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": f'DOI:"{paper.doi}"',
        "format": "json",
        "pageSize": "1",
        "resultType": "core",
    }
    req = Request(f"{endpoint}?{urlencode(params)}", headers={"User-Agent": "DailyPaperBot/1.0"}, method="GET")
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = payload.get("resultList", {}).get("result", [])
    if not result:
        return paper
    item = result[0]
    if not paper.pmcid:
        paper.pmcid = (item.get("pmcid") or "").strip()
    if not paper.url:
        urls = _extract_fulltext_urls(item)
        if urls:
            paper.url = urls[0]
    _enrich_from_epmc_fulltext_xml(paper)
    if not paper.fulltext_available:
        _enrich_from_html_fulltext(paper)
    return paper


def _first_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return _normalize("".join(node.itertext()))


def _collect_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return _normalize("".join(node.itertext()))


def _normalize(text: str) -> str:
    return " ".join(text.split())


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


def _download_html(url: str) -> str:
    try:
        req = Request(
            url,
            headers={"User-Agent": "DailyPaperBot/1.0", "Accept": "text/html,*/*;q=0.8"},
            method="GET",
        )
        with urlopen(req, timeout=20) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read().decode("utf-8", errors="ignore")
        if "html" in content_type or "<html" in raw.lower():
            return raw
        return ""
    except Exception:
        return ""


_SUPP_PATTERN = re.compile(
    r"(?i)\b(extended\s+data|supplementary|supplement|extended\s+figure|fig\.\s*s\d|figure\s*s\d)",
)


def _is_supplementary_label(label: str) -> bool:
    """Return True when the figure label belongs to a supplement / extended-data section."""
    return bool(_SUPP_PATTERN.search(label))


def _extract_figures_from_epmc_xml(paper: Paper, max_figures: int) -> list[str]:
    if paper.source != "europe_pmc" or not paper.pmcid:
        return []
    try:
        endpoint = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{paper.pmcid}/fullTextXML"
        req = Request(endpoint, headers={"User-Agent": "DailyPaperBot/1.0"}, method="GET")
        with urlopen(req, timeout=25) as resp:
            xml_text = resp.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(xml_text)
        captions: list[str] = []
        for fig in root.findall(".//fig"):
            label = _first_text(fig.find("label"))
            # Skip Extended Data / Supplementary figures.
            if _is_supplementary_label(label):
                continue
            # Also skip if the figure's ancestor section looks supplementary.
            caption_node = fig.find("caption")
            caption = _collect_text(caption_node)
            if not caption:
                continue
            prefix = f"{label}: " if label else ""
            captions.append(_normalize(f"{prefix}{caption}"))
            if len(captions) >= max_figures:
                break
        return captions
    except Exception:
        return []


_SUPP_CONTEXT_RE = re.compile(
    r"(?i)(extended[\s\-]data|supplementary|fig\.?\s*s\d|figure\s*s\d)",
)


def _extract_figures_from_html(paper: Paper, max_figures: int) -> list[str]:
    candidates = [paper.url, f"https://doi.org/{paper.doi}" if paper.doi else ""]
    for url in candidates:
        if not url:
            continue
        html = _download_html(url)
        if not html:
            continue
        pattern = re.compile(r"(?i)(?:figure|fig\.)\s*\d+[^<\n]{10,300}")
        cleaned: list[str] = []
        for m in pattern.finditer(html):
            # Check 60 chars of context before the match to exclude supp/extended figures.
            context_before = html[max(0, m.start() - 60) : m.start()]
            if _SUPP_CONTEXT_RE.search(context_before):
                continue
            text = _normalize(m.group())
            if _SUPP_CONTEXT_RE.search(text[:60]):
                continue
            if len(text) > 15 and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= max_figures:
                break
        if not cleaned:
            # Fallback with explicit capture blocks, same filtering.
            for m in re.finditer(r"(?i)(?:figure|fig\.)\s*\d+[:.\- ]{0,2}[^<]{20,260}", html):
                context_before = html[max(0, m.start() - 60) : m.start()]
                if _SUPP_CONTEXT_RE.search(context_before):
                    continue
                text = _normalize(m.group())
                if _SUPP_CONTEXT_RE.search(text[:60]):
                    continue
                if len(text) > 15 and text not in cleaned:
                    cleaned.append(text)
                if len(cleaned) >= max_figures:
                    break
        if cleaned:
            return cleaned
    return []


def _enrich_from_epmc_fulltext_xml(paper: Paper) -> None:
    if not paper.pmcid:
        return
    try:
        endpoint = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{paper.pmcid}/fullTextXML"
        req = Request(endpoint, headers={"User-Agent": "DailyPaperBot/1.0"}, method="GET")
        with urlopen(req, timeout=25) as resp:
            xml_text = resp.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(xml_text)

        aff_values = _extract_affiliations_from_xml(root)
        if aff_values:
            paper.affiliations = aff_values

        # Try to resolve per-author affiliations from JATS author/xref/aff structure.
        first_aff, last_aff = _extract_first_last_author_affs(root)
        if first_aff and not paper.first_author_affiliation:
            paper.first_author_affiliation = first_aff
        if last_aff and not paper.last_author_affiliation:
            paper.last_author_affiliation = last_aff
        # Fallback: use the ordered affiliations list when per-author data is unavailable.
        if not paper.first_author_affiliation and aff_values:
            paper.first_author_affiliation = aff_values[0]
        if not paper.last_author_affiliation and aff_values:
            paper.last_author_affiliation = aff_values[-1]

        if not paper.abstract:
            abstract_text = _collect_text(root.find(".//abstract"))
            if abstract_text:
                paper.abstract = abstract_text

        methods_excerpt = _extract_methods_excerpt(root)
        if methods_excerpt:
            paper.methods_excerpt = methods_excerpt
            paper.fulltext_available = True
        else:
            body_text = _collect_text(root.find(".//body"))
            paper.fulltext_available = len(body_text) > 1000
    except Exception:
        paper.fulltext_available = False


def _extract_affiliations_from_xml(root: ET.Element) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for aff in root.findall(".//aff"):
        text = _collect_text(aff)
        if text and text not in seen:
            seen.add(text)
            values.append(text)
        if len(values) >= 6:
            break
    return values


def _extract_first_last_author_affs(root: ET.Element) -> tuple[str, str]:
    """Parse JATS XML to get first and last (corresponding) author affiliations.

    JATS pattern:
        <contrib contrib-type="author"><xref ref-type="aff" rid="aff1"/></contrib>
        <aff id="aff1">Harvard Medical School...</aff>
    """
    # Build id -> text map for all <aff> elements in the document.
    aff_map: dict[str, str] = {}
    for aff_el in root.findall(".//aff"):
        aff_id = aff_el.get("id", "")
        text = _collect_text(aff_el)
        if aff_id and text:
            aff_map[aff_id] = text

    contribs = root.findall('.//contrib[@contrib-type="author"]')
    if not contribs:
        return "", ""

    def _contrib_aff(contrib: ET.Element) -> str:
        for xref in contrib.findall('.//xref[@ref-type="aff"]'):
            rid = xref.get("rid", "")
            if rid in aff_map:
                return aff_map[rid]
        # Some JATS files embed <aff> directly inside <contrib>.
        aff_el = contrib.find(".//aff")
        if aff_el is not None:
            return _collect_text(aff_el)
        return ""

    first = _contrib_aff(contribs[0])
    last = _contrib_aff(contribs[-1])
    return first, last


def _extract_methods_excerpt(root: ET.Element) -> str:
    # Common JATS pattern: sec/title contains Methods or Materials and Methods.
    for sec in root.findall(".//sec"):
        title = _collect_text(sec.find("title")).lower()
        if not title:
            continue
        if "method" in title or "materials" in title or "实验" in title or "方法" in title:
            text = _collect_text(sec)
            if len(text) > 120:
                return text[:2500]
    return ""


def _enrich_from_html_fulltext(paper: Paper) -> None:
    candidates = [paper.url, f"https://doi.org/{paper.doi}" if paper.doi else ""]
    for url in candidates:
        if not url:
            continue
        html = _download_html(url)
        if not html:
            continue
        plain = _html_to_text(html)
        if len(plain) < 1800:
            continue
        methods_excerpt = _extract_methods_from_text(plain)
        if methods_excerpt:
            paper.methods_excerpt = methods_excerpt
        if not paper.abstract:
            paper.abstract = _extract_abstract_from_text(plain)
        # Try to populate affiliations when XML path was unavailable.
        if not paper.affiliations:
            paper.affiliations = _extract_affiliations_from_plain(plain)
        if paper.affiliations:
            if not paper.first_author_affiliation:
                paper.first_author_affiliation = paper.affiliations[0]
            if not paper.last_author_affiliation:
                paper.last_author_affiliation = paper.affiliations[-1]
        paper.fulltext_available = True
        return


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return _normalize(text)


def _extract_methods_from_text(text: str) -> str:
    pattern = re.compile(
        r"(?is)(materials and methods|methods|methodology)\s*[:\-]?\s*(.{200,3000}?)(results|discussion|conclusion|references)",
    )
    match = pattern.search(text)
    if match:
        return _normalize(match.group(2))[:2500]
    return ""


def _extract_abstract_from_text(text: str) -> str:
    pattern = re.compile(r"(?is)(abstract)\s*[:\-]?\s*(.{80,1200}?)(introduction|background|methods)")
    match = pattern.search(text)
    if match:
        return _normalize(match.group(2))[:1200]
    return ""


_INST_KW_RE = re.compile(
    r"\b(university|institute|school of|college of|hospital|department of|"
    r"center for|centre for|laboratory of|faculty of|academy of)\b",
    re.IGNORECASE,
)


def _extract_affiliations_from_plain(text: str) -> list[str]:
    """Heuristic: extract lines/phrases that look like institutional affiliations."""
    found: list[str] = []
    seen: set[str] = set()
    # Split on semicolons, newlines, or numbered list markers.
    chunks = re.split(r"[;\n]|\s{2,}", text[:6000])
    for chunk in chunks:
        chunk = _normalize(chunk)
        if len(chunk) < 15 or len(chunk) > 280:
            continue
        if not _INST_KW_RE.search(chunk):
            continue
        key = chunk[:80].lower()
        if key not in seen:
            seen.add(key)
            found.append(chunk)
        if len(found) >= 6:
            break
    return found

