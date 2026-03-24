from __future__ import annotations

from typing import Any

from daily_paper.models import Paper


def build_digest_text(
    paper: Paper,
    config: dict[str, Any],
    figure_captions: list[str] | None = None,
) -> str:
    interpretation_cfg = config["interpretation"]
    abstract = paper.abstract or "暂无摘要，建议点击链接查看原文。"

    journal_name = paper.journal.title() if paper.journal else "白名单期刊（具体名称待源数据补全）"
    background = f"该研究发表于 {journal_name}，主题与生物信息/测序/遗传学分析方向相关。"
    methods = _extract_method_sentence(paper.methods_excerpt or abstract[:400])
    impact = "研究结果对数据分析流程优化、方法学复用或遗传机制解析具有参考价值。"

    aff_display = _format_key_affiliations(paper)
    abstract_short = abstract[: interpretation_cfg["max_chars"]]

    body_lines = [
        f"## 论文标题",
        f"{paper.title}",
        "",
        f"## 基本信息",
        f"- DOI：{paper.doi}",
        f"- 期刊：{paper.journal or '未知期刊'}",
        f"- 发表时间：{paper.published_at.date().isoformat()}",
        f"- 引用数：{paper.citations}",
        f"- {aff_display}",
        f"- 链接：{paper.url}",
        "",
        "## 目的与背景",
        background,
        "",
        "## 方法",
        methods,
        "",
        "## 结果",
        f"（摘要摘录）{abstract_short}",
        "",
        "## 意义",
        impact,
        "",
        "## 三条要点",
        f"1. {_safe_bullet(paper.title)}",
        f"2. 发表于 {paper.journal or '未知期刊'}，引用数 {paper.citations}。",
        f"3. 访问链接：{paper.url}",
    ]
    if figure_captions:
        body_lines.extend(["", "## 按图解读"])
        for idx, caption in enumerate(figure_captions, start=1):
            body_lines.append(f"- Figure {idx}: {caption}")
    return "\n".join(body_lines)


def _extract_method_sentence(abstract: str) -> str:
    if not abstract:
        return "摘要信息不足，建议重点关注原文中的数据来源、算法框架与验证策略。"
    for sep in (". ", "。", "; "):
        parts = abstract.split(sep)
        if len(parts) > 1:
            return f"摘要提示核心方法为：{parts[0].strip()}。"
    return f"摘要提示核心方法为：{abstract.strip()}"


def _safe_bullet(text: str) -> str:
    return " ".join(text.split())


def _format_key_affiliations(paper: Paper) -> str:
    """Return 'first-author unit / last-author (corresponding) unit'."""
    first = paper.first_author_affiliation.strip()
    last = paper.last_author_affiliation.strip()
    if first and last and first != last:
        return f"第一作者：{first}；通讯作者：{last}"
    if first:
        return f"第一作者：{first}"
    if last:
        return f"通讯作者：{last}"
    # Fall back to the deduplicated affiliations list when per-author data is absent.
    if paper.affiliations:
        return paper.affiliations[0]
    return "未提供"

