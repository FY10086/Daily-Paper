from __future__ import annotations

import html as _html_mod
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Sequence


def send_email(
    host: str,
    port: int,
    username: str,
    password: str,
    sender: str,
    recipients: Sequence[str],
    subject: str,
    body: str,
) -> None:
    html_body = _md_to_html(body)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    # Plain-text fallback (strip markdown symbols for cleaner reading).
    plain = _strip_md_symbols(body)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(host=host, port=port, timeout=20) as server:
        server.login(username, password)
        server.sendmail(sender, list(recipients), msg.as_string())


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:"Helvetica Neue",Arial,"PingFang SC","Microsoft YaHei",sans-serif;
        background:#f4f6f9;margin:0;padding:16px;color:#2c3e50;}}
  .wrap{{max-width:760px;margin:0 auto;background:#fff;border-radius:8px;
         padding:28px 36px;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
  h1{{font-size:20px;color:#1a3c5e;border-bottom:3px solid #2980b9;
      padding-bottom:10px;margin-top:0;line-height:1.4;}}
  h2{{font-size:15px;color:#fff;background:#2980b9;padding:6px 12px;
      border-radius:4px;margin:20px 0 8px;}}
  h3{{font-size:14px;color:#2c3e50;border-left:3px solid #2980b9;
      padding-left:8px;margin:14px 0 6px;}}
  p{{font-size:14px;line-height:1.8;margin:6px 0;}}
  ul,ol{{padding-left:22px;margin:4px 0;}}
  li{{font-size:14px;line-height:1.8;}}
  hr{{border:none;border-top:1px solid #e0e0e0;margin:18px 0;}}
  .meta{{background:#f0f7ff;border-left:4px solid #2980b9;padding:10px 14px;
         border-radius:0 4px 4px 0;font-size:13px;color:#555;margin:12px 0;}}
  .fig{{background:#fafafa;border:1px solid #e8e8e8;border-radius:4px;
        padding:8px 12px;margin:6px 0;font-size:13px;color:#444;}}
  a{{color:#2980b9;text-decoration:none;}}
  strong{{color:#1a3c5e;}}
</style>
</head>
<body>
<div class="wrap">
{body}
</div>
</body>
</html>
"""


def _md_to_html(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False
    in_fig = False  # figure-block section

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for line in lines:
        # --- headings ---
        if line.startswith("### "):
            close_lists()
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            close_lists()
            content = _inline(line[3:])
            # First h2 with 论文标题 → render as h1
            if "论文标题" in content:
                out.append(f"<h1>{_inline(line[3:].replace('论文标题', '').strip())}</h1>")
            else:
                out.append(f"<h2>{content}</h2>")
        # --- horizontal rule ---
        elif line.strip() == "---":
            close_lists()
            out.append("<hr>")
        # --- unordered list ---
        elif re.match(r"^[*\-] ", line):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        # --- ordered list ---
        elif re.match(r"^\d+\.\s", line):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            content = re.sub(r"^\d+\.\s*", "", line)
            out.append(f"<li>{_inline(content)}</li>")
        # --- blank line ---
        elif line.strip() == "":
            close_lists()
            out.append("")
        # --- figure caption lines (heuristic) ---
        elif re.match(r"(?i)^(figure|fig\.)\s*\d+", line.strip()):
            close_lists()
            out.append(f'<div class="fig">{_inline(line)}</div>')
        # --- paragraph ---
        else:
            close_lists()
            out.append(f"<p>{_inline(line)}</p>")

    close_lists()
    body_html = "\n".join(out)
    return _HTML_TEMPLATE.format(body=body_html)


def _inline(text: str) -> str:
    """Apply inline Markdown (bold, italic, links) and HTML-escape the rest."""
    # Escape HTML first, then restore markdown patterns we handle.
    escaped = _html_mod.escape(text)
    # Links: [text](url) — note we escaped & → &amp; etc., URL should be fine.
    escaped = re.sub(r"\[(.+?)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', escaped)
    # Bold **text** or __text__
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    # Italic *text* or _text_  (single, not double)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
    # Inline code `text`
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    # Bare URLs
    escaped = re.sub(
        r"(?<!['\">])(https?://\S+)",
        r'<a href="\1">\1</a>',
        escaped,
    )
    return escaped


def _strip_md_symbols(text: str) -> str:
    """Remove Markdown decoration for plain-text fallback."""
    text = re.sub(r"^#{1,3}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", text)
    return text
