from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env")
    _load_env_file(root / ".env.local")

    parser = argparse.ArgumentParser(description="Daily Paper MVP runner")
    parser.add_argument(
        "--config",
        default="config/default_config.json",
        help="Path to config json file",
    )
    parser.add_argument(
        "--sent-log",
        default="data/sent_papers.txt",
        help="Path to sent DOI log",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect/rank only, do not send email or write sent log",
    )
    args = parser.parse_args()

    src_path = root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from daily_paper.config import load_config
    from daily_paper.pipeline import run_pipeline

    config = load_config(root / args.config)
    smtp_config = None if args.dry_run else _load_smtp_config(config)
    llm_config = _load_llm_config(config)

    result = run_pipeline(
        config=config,
        sent_log_path=str(root / args.sent_log),
        smtp_config=smtp_config,
        llm_config=llm_config,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _load_smtp_config(config: dict) -> dict[str, str]:
    raw = dict(config.get("smtp", {}))
    env_sender = os.getenv("SMTP_SENDER", "").strip()
    env_user = os.getenv("SMTP_USER", "").strip()
    cfg_sender = str(raw.get("sender", "")).strip()
    cfg_user = str(raw.get("username", "")).strip()
    smtp = {
        "host": str(raw.get("host", os.getenv("SMTP_HOST", ""))).strip(),
        "port": str(raw.get("port", os.getenv("SMTP_PORT", ""))).strip(),
        "username": cfg_user or env_user,
        "password": str(raw.get("password", os.getenv("SMTP_PASS", ""))).strip(),
        "sender": _choose_sender(cfg_sender, env_sender, cfg_user, env_user),
    }
    missing = [key for key, value in smtp.items() if not value]
    if missing:
        raise RuntimeError("Missing SMTP fields in config/env: " + ", ".join(missing))
    if not _looks_like_email(smtp["sender"]):
        raise RuntimeError("SMTP sender must be a valid email address")
    if not _looks_like_email(smtp["username"]):
        raise RuntimeError("SMTP username must be a valid email address")
    return smtp


def _load_llm_config(config: dict) -> dict[str, str] | None:
    raw = dict(config.get("llm", {}))
    provider = str(raw.get("provider", os.getenv("LLM_PROVIDER", "openrouter"))).strip()
    default_env_key = "OPENROUTER_API_KEY" if provider == "openrouter" else "DEEPSEEK_API_KEY"
    api_key = str(raw.get("api_key", os.getenv(default_env_key, ""))).strip()
    if not api_key:
        return None

    return {
        "provider": provider,
        "api_key": api_key,
        "model": str(raw.get("model", os.getenv("LLM_MODEL", "openai/gpt-5.2"))).strip(),
        "base_url": _resolve_base_url(provider, raw),
        "http_referer": str(raw.get("http_referer", os.getenv("OPENROUTER_HTTP_REFERER", ""))).strip(),
        "app_title": str(raw.get("app_title", os.getenv("OPENROUTER_APP_TITLE", "Daily Paper"))).strip(),
    }


def _resolve_base_url(provider: str, raw: dict) -> str:
    from_env = os.getenv("LLM_BASE_URL", "").strip()
    from_cfg = str(raw.get("base_url", "")).strip()
    if from_cfg:
        return from_cfg
    if from_env:
        return from_env
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    if provider == "deepseek":
        return "https://api.deepseek.com"
    return ""


def _choose_sender(cfg_sender: str, env_sender: str, cfg_user: str, env_user: str) -> str:
    for value in (cfg_sender, env_sender, cfg_user, env_user):
        if _looks_like_email(value):
            return value
    return cfg_sender or env_sender or cfg_user or env_user


def _looks_like_email(value: str) -> bool:
    text = value.strip()
    if "@" not in text or "." not in text:
        return False
    if " " in text:
        return False
    return True


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    sys.exit(main())

