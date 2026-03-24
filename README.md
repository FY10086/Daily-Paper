# Daily Paper MVP

每天自动筛选 1 篇生物信息/测序/数据库相关高质量论文，生成结构化解读并通过邮件发送。
当前版本支持：严格期刊白名单过滤、仅选择可解析全文的研究文章、按 Figure 顺序增强解读（可提取时）、OpenRouter 模型解读。

## 项目结构

- `daily_run.py`：单次执行入口
- `config.demo/default_config.json`：公开示例配置模板
- `src/daily_paper/collectors`：数据源抓取（Europe PMC / Crossref）
- `src/daily_paper/ranker`：评分与Top1选择
- `src/daily_paper/dedup`：已发送 DOI 去重
- `src/daily_paper/digest`：解读文本生成
- `src/daily_paper/mailer`：SMTP 发送
- `data/sent_papers.txt`：已发送 DOI 记录

## 运行要求

- Python 3.10+
- 可访问 `Europe PMC` 与 `Crossref` API
- 首次使用时，将 `config.demo/default_config.json` 复制为 `config/default_config.json`
- 在本地 `config/default_config.json` 中填写 `smtp` 与 `llm` 参数
- 也支持 `.env` 覆盖（可参考 `.env.example`）

## 快速开始

1. 最简模式（推荐）

- 程序会自动读取项目根目录下 `.env` / `.env.local`
- 你只需要执行命令，不用每次 `export`

```bash
cp config.demo/default_config.json config/default_config.json
python3 daily_run.py --dry-run
python3 daily_run.py
```

2. 仅验证抓取与筛选（不发邮件）：

```bash
python3 daily_run.py --dry-run
```

3. OpenRouter（默认）：

```bash
# 先复制 config.demo/default_config.json 到 config/default_config.json
# 再在 config/default_config.json 中设置
# llm.provider = "openrouter"
# llm.model = "openai/gpt-5.2"
# llm.api_key = "你的OPENROUTER_API_KEY"
```

## 验证标准（MVP）

- 命令 `python3 daily_run.py --dry-run` 成功返回 JSON
- 返回字段包含 `status / paper / subject / recipients / digest_preview`
- 若来源可解析图注，返回字段会包含 `figure_count > 0`
- 若当前窗口内没有“可解析全文且满足研究类型”的论文，会返回 `status=empty`
- 正式运行成功后，`data/sent_papers.txt` 新增 1 条 DOI
- 连续运行两次，不会重复写入同一 DOI

## 去重策略

- 程序发送成功后会把 DOI 写入 `data/sent_papers.txt`
- 后续运行会自动跳过该 DOI

## 可调参数

- 关键词：`config/default_config.json -> topic_keywords`
- 时间窗口：`time_window.primary_days / fallback_days`
- 期刊白名单与权重：`journals.whitelist`
- 白名单兜底策略：`journals.allow_non_whitelist_fallback`
- 收件人：`delivery.recipients`
- SMTP 参数：`smtp.host / smtp.port / smtp.username / smtp.password / smtp.sender`
- LLM 参数：`llm.provider / llm.api_key / llm.model / llm.base_url`
- 全文硬过滤与研究类型过滤：`content.require_full_text / content.include_any / content.exclude_any`
- Figure 最大提取数量：`interpretation.max_figures`
