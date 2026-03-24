from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from daily_paper.models import Paper


def build_digest_with_deepseek(
    paper: Paper,
    llm_cfg: dict[str, Any],
    figure_captions: list[str] | None = None,
    timeout: int = 25,
) -> str:
    api_key = llm_cfg["api_key"]
    model = llm_cfg.get("model", "deepseek-chat")
    base_url = llm_cfg.get("base_url", "https://api.deepseek.com")
    endpoint = base_url.rstrip("/") + "/chat/completions"

    prompt = _build_prompt(paper, figure_captions or [])
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是生物信息学论文解读助手。输出中文，结构清晰，避免编造未给出的实验细节。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError("DeepSeek response has no choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("DeepSeek response content is empty")
    return content


def _build_prompt(paper: Paper, figure_captions: list[str]) -> str:
    figure_block = "未提取到 figure 信息。"
    if figure_captions:
        lines = [f"Figure {idx}: {caption}" for idx, caption in enumerate(figure_captions, start=1)]
        figure_block = "\n".join(lines)
    return (
        "请基于以下论文信息，生成结构化中文解读。\n"
        "输出格式必须严格为：\n"
        "论文标题：...\n"
        "DOI：...\n"
        "\n"
        "【背景】\n"
        "...\n"
        "\n"
        "【方法】\n"
        "...\n"
        "\n"
        "【意义】\n"
        "...\n"
        "\n"
        "【三条要点】\n"
        "- ...\n"
        "- ...\n"
        "- ...\n"
        "\n"
        "【按图解读】\n"
        "Figure 1: ...\n"
        "Figure 2: ...\n"
        "（按给定 figure 顺序组织，如果没有 figure 则说明无法按图展开）\n"
        "\n"
        "限制：只基于给定信息，不要编造具体数据。\n"
        f"标题：{paper.title}\n"
        f"DOI：{paper.doi}\n"
        f"期刊：{paper.journal or '未知'}\n"
        f"发表时间：{paper.published_at.date().isoformat()}\n"
        f"摘要：{paper.abstract or '暂无摘要'}\n"
        f"方法片段：{paper.methods_excerpt or '未提取到methods段落'}\n"
        f"Figure信息：\n{figure_block}\n"
        f"链接：{paper.url}\n"
    )

