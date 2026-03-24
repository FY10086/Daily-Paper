from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from daily_paper.models import Paper


def build_digest_with_openrouter(
    paper: Paper,
    llm_cfg: dict[str, Any],
    figure_captions: list[str] | None = None,
    timeout: int = 90,
) -> str:
    api_key = llm_cfg["api_key"]
    endpoint = llm_cfg.get("base_url", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    model = llm_cfg.get("model", "openai/gpt-5.2")
    referer = llm_cfg.get("http_referer", "")
    title = llm_cfg.get("app_title", "Daily Paper")
    prompt = _build_prompt(paper, figure_captions or [])

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是生物信息论文解读助手。必须使用中文输出，内容可信，不编造实验结果。"
                    "输出格式为 Markdown，使用 ## 作为一级章节标题，### 作为小节标题，"
                    "- 作为列表项，**加粗**标注关键术语。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title

    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError("OpenRouter response has no choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("OpenRouter response content is empty")
    return content


def _build_prompt(paper: Paper, figure_captions: list[str]) -> str:
    if figure_captions:
        fig_lines = "\n".join([f"Figure {i}: {cap}" for i, cap in enumerate(figure_captions, start=1)])
    else:
        fig_lines = "（未提取到正文图注，按图解读部分请说明无法展开。）"

    # Affiliation: prefer per-author fields, fall back to all-affiliations list.
    first_aff = paper.first_author_affiliation or (paper.affiliations[0] if paper.affiliations else "未提供")
    last_aff = (
        paper.last_author_affiliation
        or (paper.affiliations[-1] if len(paper.affiliations) > 1 else first_aff)
        or "未提供"
    )

    return (
        "请基于下面的论文信息，用中文输出结构化解读，使用 Markdown 格式。\n\n"
        "【章节格式规范】严格按以下顺序与名称输出，每个章节标题只写 ## 后面的名称，"
        "不添加破折号、括号或任何说明性文字：\n"
        "1. ## 论文标题\n"
        "   · 第一行输出论文英文原标题（不加引号）\n"
        "   · 第二行输出中文翻译标题\n"
        "2. ## 基本信息\n"
        "   · DOI、期刊、发表时间与工作单位\n"
        "3. ## 目的与背景\n"
        "   · 研究动机、领域现状与本文要解决的核心问题\n"
        "4. ## 方法\n"
        "   · 关键技术路线与实验设计\n"
        "5. ## 结果\n"
        "   · 主要发现与结论\n"
        "6. ## 意义\n"
        "   · 科学价值、潜在应用与局限性\n"
        "7. ## 三条要点\n"
        "   · 三句话让你读懂本篇论文（带序号）\n"
        "8. ## 主要图解\n"
        "===== 论文信息 =====\n"
        f"英文标题：{paper.title}\n"
        f"DOI：{paper.doi}\n"
        f"期刊：{paper.journal or '未知'}\n"
        f"发表时间：{paper.published_at.date().isoformat()}\n"
        f"第一作者单位：{first_aff}\n"
        f"通讯作者单位：{last_aff}\n"
        f"链接：{paper.url}\n\n"
        f"摘要：\n{paper.abstract or '暂无摘要'}\n\n"
        f"方法片段：\n{paper.methods_excerpt or '（未提取到 Methods 段落）'}\n\n"
        f"正文图注：\n{fig_lines}\n"
    )

