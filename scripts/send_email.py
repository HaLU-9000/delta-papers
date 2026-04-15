#!/usr/bin/env python3
"""Send a Markdown digest report via Gmail SMTP.

Self-contained: uses only Python 3 stdlib.
"""
import argparse
import json
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path


# Material Symbols Outlined (Google Fonts) — inlined as SVG for reliable email
# rendering (Gmail strips external font links). Each icon is a 24x24 SVG path
# from the official Material Symbols set. We render them inline so they look
# like Material Design icons regardless of client font support.
MATERIAL_ICON_SVGS = {
    "public": (  # used for 分野全体の動向 (globe)
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="#1a73e8" style="vertical-align:-4px;margin-right:6px">'
        '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.93 6h-2.95a15.65 15.65 0 0 0-1.38-3.56'
        'A8.03 8.03 0 0 1 18.93 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96z'
        'M4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2 0 .68.06 1.34.14 2H4.26z'
        'm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56A7.99 7.99 0 0 1 5.08 16zm2.95-8H5.08a7.99 7.99 0 0 1 '
        '4.33-3.56A15.65 15.65 0 0 0 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 '
        '2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2 0-.68.07-1.35.16-2h4.68c.09.65.16 1.32.16 '
        '2 0 .68-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 0 1-4.33 3.56z'
        'M16.36 14c.08-.66.14-1.32.14-2 0-.68-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z"/>'
        '</svg>'
    ),
    "folder_open": (  # used for Project
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="#f9a825" style="vertical-align:-4px;margin-right:6px">'
        '<path d="M19 20H4c-1.11 0-2-.9-2-2V6c0-1.1.89-2 2-2h6l2 2h7a2 2 0 0 1 2 2H4v10l2.14-8h17.07'
        'l-2.28 8.5c-.23.87-1.01 1.5-1.93 1.5z"/></svg>'
    ),
    "bar_chart": (  # used for Statistics
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="#34a853" style="vertical-align:-4px;margin-right:6px">'
        '<path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>'
    ),
}

# Emoji -> Material Symbols name. Replaced post-rendering in HTML.
EMOJI_TO_ICON = {
    "🌐": "public",
    "📂": "folder_open",
    "📊": "bar_chart",
}


HTML_TEMPLATE = (
    '<html><head><meta charset="utf-8">'
    # Material Symbols stylesheet — works in clients that allow external CSS
    # (e.g. Apple Mail). For Gmail/Outlook the inline SVGs above are the
    # rendering path, but loading the font lets supporting clients use the
    # vector font glyphs if we ever switch to <span class="material-symbols-outlined">.
    '<link rel="stylesheet" '
    'href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined&family=Roboto:wght@400;500;700&display=swap">'
    '<style>'
    'body{font-family:Roboto,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
    'max-width:780px;margin:24px auto;padding:0 16px;color:#202124;line-height:1.55} '
    'h1,h2,h3{color:#202124;font-weight:500} '
    'h2{border-bottom:1px solid #e8eaed;padding-bottom:6px;margin-top:32px;display:flex;align-items:center} '
    'a{color:#1a73e8;text-decoration:none} a:hover{text-decoration:underline} '
    'code{background:#f1f3f4;padding:2px 5px;border-radius:3px;font-size:90%;font-family:"Roboto Mono",monospace} '
    'pre{background:#f1f3f4;padding:12px;border-radius:6px;overflow-x:auto} '
    'blockquote{border-left:3px solid #1a73e8;padding-left:12px;color:#5f6368;margin-left:0;background:#f8f9fa;padding:8px 12px;border-radius:0 4px 4px 0} '
    'hr{border:none;border-top:1px solid #e8eaed;margin:24px 0} '
    'ul,ol{padding-left:24px} '
    '.material-symbols-outlined{font-family:"Material Symbols Outlined";font-weight:normal;font-style:normal;'
    'font-size:22px;line-height:1;letter-spacing:normal;text-transform:none;display:inline-block;'
    'white-space:nowrap;word-wrap:normal;direction:ltr;vertical-align:-4px;margin-right:6px} '
    '</style></head><body>{HTML}</body></html>'
)


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


def apply_inline(text: str) -> str:
    """Apply inline markdown transforms on already-HTML-escaped text.

    Order matters: code spans first (so their content isn't touched),
    then links, then bold, then italic.
    """
    # Protect code spans by extracting placeholders
    code_spans: list[str] = []

    def _code_sub(m: re.Match) -> str:
        code_spans.append(m.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _code_sub, text)

    # Links: [text](url) — text and url are already escaped
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        text,
    )

    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    # Italic *text* (single asterisk, non-greedy, not empty)
    text = re.sub(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)", r"<em>\1</em>", text)

    # Restore code spans
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return f"<code>{code_spans[idx]}</code>"

    text = re.sub(r"\x00CODE(\d+)\x00", _restore, text)
    return text


def markdown_to_html(md: str) -> str:
    """Minimal Markdown to HTML converter."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    # List state
    list_type: str | None = None  # 'ul' or 'ol'
    in_paragraph = False
    paragraph_buf: list[str] = []
    in_blockquote = False
    blockquote_buf: list[str] = []

    def close_list():
        nonlocal list_type
        if list_type is not None:
            out.append(f"</{list_type}>")
            list_type = None

    def close_paragraph():
        nonlocal in_paragraph, paragraph_buf
        if in_paragraph:
            joined = " ".join(paragraph_buf)
            out.append(f"<p>{apply_inline(joined)}</p>")
            paragraph_buf = []
            in_paragraph = False

    def close_blockquote():
        nonlocal in_blockquote, blockquote_buf
        if in_blockquote:
            joined = " ".join(blockquote_buf)
            out.append(f"<blockquote>{apply_inline(joined)}</blockquote>")
            blockquote_buf = []
            in_blockquote = False

    def close_all():
        close_paragraph()
        close_blockquote()
        close_list()

    while i < n:
        raw = lines[i]
        # Detect code fence on the ORIGINAL (unescaped) line
        if raw.lstrip().startswith("```"):
            close_all()
            # consume until closing fence
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            # skip closing fence
            if i < n:
                i += 1
            code_content = html_escape("\n".join(code_lines))
            out.append(f"<pre><code>{code_content}</code></pre>")
            continue

        # Escape line for all other processing
        line = html_escape(raw)
        stripped = line.strip()

        # Blank line — end paragraph/blockquote/list
        if stripped == "":
            close_all()
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}", raw.strip()):
            close_all()
            out.append("<hr>")
            i += 1
            continue

        # Headings (check raw for # prefix — escaping preserves #)
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            close_all()
            level = len(m.group(1))
            content = apply_inline(m.group(2))
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith("&gt; "):
            close_paragraph()
            close_list()
            if not in_blockquote:
                in_blockquote = True
            blockquote_buf.append(stripped[5:])
            i += 1
            continue
        elif stripped == "&gt;":
            close_paragraph()
            close_list()
            if not in_blockquote:
                in_blockquote = True
            blockquote_buf.append("")
            i += 1
            continue
        else:
            close_blockquote()

        # Unordered list item
        um = re.match(r"^-\s+(.*)$", stripped)
        if um:
            close_paragraph()
            if list_type != "ul":
                close_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{apply_inline(um.group(1))}</li>")
            i += 1
            continue

        # Ordered list item
        om = re.match(r"^\d+\.\s+(.*)$", stripped)
        if om:
            close_paragraph()
            if list_type != "ol":
                close_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{apply_inline(om.group(1))}</li>")
            i += 1
            continue

        # Regular paragraph line
        close_list()
        in_paragraph = True
        paragraph_buf.append(stripped)
        i += 1

    close_all()
    return "\n".join(out)


def replace_emojis_with_icons(html: str) -> str:
    """Swap emoji markers in the rendered HTML for inline Material Symbols SVGs."""
    for emoji, icon_name in EMOJI_TO_ICON.items():
        svg = MATERIAL_ICON_SVGS.get(icon_name, "")
        if svg:
            html = html.replace(emoji, svg)
    return html


def build_html(md_text: str) -> str:
    body = markdown_to_html(md_text)
    body = replace_emojis_with_icons(body)
    return HTML_TEMPLATE.replace("{HTML}", body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Markdown digest via Gmail SMTP.")
    parser.add_argument("--config", required=True, help="Path to JSON config")
    parser.add_argument("--markdown", required=True, help="Path to Markdown file")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--dry-run", action="store_true", help="Print subject+HTML instead of sending")
    args = parser.parse_args()

    md_path = Path(args.markdown)
    try:
        md_text = md_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Failed to read markdown: {e}", file=sys.stderr)
        return 1

    html = build_html(md_text)

    if args.dry_run:
        print(f"Subject: {args.subject}")
        print("---HTML---")
        print(html)
        return 0

    cfg_path = Path(args.config)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"Failed to read config: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Invalid JSON config: {e}", file=sys.stderr)
        return 1

    gmail_user = cfg.get("gmail_user")
    app_password = cfg.get("gmail_app_password")
    to_addr = cfg.get("to", gmail_user)

    if not gmail_user or not app_password:
        print("Config must contain gmail_user and gmail_app_password", file=sys.stderr)
        return 1

    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"] = formataddr(("\u0394Papers Digest", gmail_user))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(md_text)
    msg.add_alternative(html, subtype="html")

    # Attach the original Markdown file so the recipient can save / re-read it.
    try:
        md_bytes = md_path.read_bytes()
        msg.add_attachment(
            md_bytes,
            maintype="text",
            subtype="markdown",
            filename=md_path.name,
        )
    except OSError as e:
        print(f"Warning: could not attach markdown file: {e}", file=sys.stderr)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(gmail_user, app_password)
            smtp.send_message(msg)
    except Exception as e:
        print(f"SMTP error: {e}", file=sys.stderr)
        return 1

    print(f"Sent to {to_addr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
