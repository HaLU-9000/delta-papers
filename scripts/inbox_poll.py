#!/usr/bin/env python3
"""Poll Gmail INBOX for ΔPapers digest control commands.

Reads unread messages from a trusted sender whose subject begins with
`/digest` (or `digest:`). Executes a small set of safe state-mutating
commands against `state/projects.json` and replies with the result.
LLM-driven commands like `add-project` / `run` are out of scope here.

Trigger via launchd or `python3 inbox_poll.py --once`.

Supported commands (subject line):
  /digest help
  /digest list-projects
  /digest enable-project <id-or-name>
  /digest disable-project <id-or-name>
  /digest set <project-id> <field> <value>
      e.g. /digest set inceptis-tis arxiv_lookback_hours 168
  /digest add-keyword <project-id> <keyword>
  /digest remove-keyword <project-id> <keyword>
  /digest add-author <project-id> <author>
  /digest remove-author <project-id> <author>
  /digest show-config
  /digest seen-clear <project-id>

Reply policy: every processed message gets a reply containing the result.
The original message is then marked as read.
"""
from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import shlex
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SKILL_DIR / "state"
PROJECTS_PATH = STATE_DIR / "projects.json"
CONFIG_PATH = STATE_DIR / "config.json"
SEEN_PATH = STATE_DIR / "seen_papers.json"

LIST_FIELDS = {
    "arxiv_categories", "arxiv_keywords", "biorxiv_categories",
    "medrxiv_categories", "rss_journals", "extra_rss_feeds", "authors",
}
INT_FIELDS = {
    "arxiv_lookback_hours", "biorxiv_lookback_days",
    "rss_lookback_days", "max_papers",
}
BOOL_FIELDS = {"enabled"}
STR_FIELDS = {"name", "description"}
ALL_SETTABLE = LIST_FIELDS | INT_FIELDS | BOOL_FIELDS | STR_FIELDS


def _ensure_utf8_std_streams():
    for stream in (sys.stdout, sys.stderr):
        enc = getattr(stream, "encoding", None)
        if enc and enc.lower() != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_project(projects: list[dict], key: str) -> dict | None:
    key_l = key.lower()
    for p in projects:
        if p.get("id", "").lower() == key_l or p.get("name", "").lower() == key_l:
            return p
    return None


def parse_value(field: str, raw: str):
    if field in INT_FIELDS:
        return int(raw)
    if field in BOOL_FIELDS:
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    if field in LIST_FIELDS:
        # comma-separated
        return [v.strip() for v in raw.split(",") if v.strip()]
    return raw


def cmd_help() -> str:
    return __doc__.strip()


def cmd_list_projects(projects: list[dict]) -> str:
    if not projects:
        return "(no projects)"
    lines = ["id | name | enabled | #cats | #kws"]
    for p in projects:
        cats = len(p.get("arxiv_categories") or []) + len(p.get("biorxiv_categories") or [])
        kws = len(p.get("arxiv_keywords") or [])
        enabled = p.get("enabled", True)
        lines.append(f"{p.get('id','?')} | {p.get('name','?')} | {enabled} | {cats} | {kws}")
    return "\n".join(lines)


def cmd_show_config() -> str:
    cfg = load_json(CONFIG_PATH, {})
    redacted = dict(cfg)
    if "gmail_app_password" in redacted:
        redacted["gmail_app_password"] = "***"
    return json.dumps(redacted, ensure_ascii=False, indent=2)


def cmd_set_enabled(projects: list[dict], key: str, enabled: bool) -> str:
    proj = find_project(projects, key)
    if not proj:
        return f"ERROR: project {key!r} not found"
    proj["enabled"] = enabled
    save_json(PROJECTS_PATH, projects)
    return f"OK: {proj['id']}.enabled = {enabled}"


def cmd_set_field(projects: list[dict], pid: str, field: str, raw_value: str) -> str:
    if field not in ALL_SETTABLE:
        return f"ERROR: field {field!r} not settable. Allowed: {sorted(ALL_SETTABLE)}"
    proj = find_project(projects, pid)
    if not proj:
        return f"ERROR: project {pid!r} not found"
    try:
        value = parse_value(field, raw_value)
    except ValueError as e:
        return f"ERROR: cannot parse value for {field}: {e}"
    proj[field] = value
    save_json(PROJECTS_PATH, projects)
    return f"OK: {proj['id']}.{field} = {json.dumps(value, ensure_ascii=False)}"


def cmd_modify_list(projects: list[dict], pid: str, field: str, item: str, add: bool) -> str:
    if field not in LIST_FIELDS:
        return f"ERROR: {field} is not a list field"
    proj = find_project(projects, pid)
    if not proj:
        return f"ERROR: project {pid!r} not found"
    lst = proj.setdefault(field, [])
    if add:
        if item in lst:
            return f"NOOP: {item!r} already in {proj['id']}.{field}"
        lst.append(item)
        action = "added"
    else:
        if item not in lst:
            return f"NOOP: {item!r} not in {proj['id']}.{field}"
        lst.remove(item)
        action = "removed"
    save_json(PROJECTS_PATH, projects)
    return f"OK: {action} {item!r} {'to' if add else 'from'} {proj['id']}.{field} (now {len(lst)} items)"


def cmd_seen_clear(pid: str) -> str:
    seen = load_json(SEEN_PATH, {})
    if pid not in seen:
        return f"NOOP: no seen entries for {pid!r}"
    n = len(seen[pid])
    del seen[pid]
    save_json(SEEN_PATH, seen)
    return f"OK: cleared {n} seen-paper IDs for {pid}"


def dispatch(subject: str) -> str:
    # Strip leading "/digest" or "digest:" prefixes
    s = subject.strip()
    s = re.sub(r"^(/?digest[:\s]+)", "", s, flags=re.IGNORECASE)
    if not s:
        return "ERROR: empty command. Try `/digest help`."
    try:
        tokens = shlex.split(s)
    except ValueError as e:
        return f"ERROR: bad quoting: {e}"
    cmd, *args = tokens
    cmd = cmd.lower()

    projects = load_json(PROJECTS_PATH, [])

    if cmd in ("help", "?"):
        return cmd_help()
    if cmd == "list-projects":
        return cmd_list_projects(projects)
    if cmd == "show-config":
        return cmd_show_config()
    if cmd == "enable-project":
        if len(args) != 1:
            return "USAGE: /digest enable-project <id-or-name>"
        return cmd_set_enabled(projects, args[0], True)
    if cmd == "disable-project":
        if len(args) != 1:
            return "USAGE: /digest disable-project <id-or-name>"
        return cmd_set_enabled(projects, args[0], False)
    if cmd == "set":
        if len(args) < 3:
            return "USAGE: /digest set <project-id> <field> <value>"
        return cmd_set_field(projects, args[0], args[1], " ".join(args[2:]))
    if cmd == "add-keyword":
        if len(args) != 2:
            return "USAGE: /digest add-keyword <project-id> <keyword>"
        return cmd_modify_list(projects, args[0], "arxiv_keywords", args[1], add=True)
    if cmd == "remove-keyword":
        if len(args) != 2:
            return "USAGE: /digest remove-keyword <project-id> <keyword>"
        return cmd_modify_list(projects, args[0], "arxiv_keywords", args[1], add=False)
    if cmd == "add-author":
        if len(args) != 2:
            return "USAGE: /digest add-author <project-id> <author>"
        return cmd_modify_list(projects, args[0], "authors", args[1], add=True)
    if cmd == "remove-author":
        if len(args) != 2:
            return "USAGE: /digest remove-author <project-id> <author>"
        return cmd_modify_list(projects, args[0], "authors", args[1], add=False)
    if cmd == "seen-clear":
        if len(args) != 1:
            return "USAGE: /digest seen-clear <project-id>"
        return cmd_seen_clear(args[0])
    return f"ERROR: unknown command {cmd!r}. Try `/digest help`."


def send_reply(cfg: dict, to_addr: str, in_reply_to: str | None, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr(("ΔPapers Digest", cfg["gmail_user"]))
    msg["To"] = to_addr
    msg["Subject"] = "Re: " + subject if not subject.lower().startswith("re:") else subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="digest.local")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(cfg["gmail_user"], cfg["gmail_app_password"])
        s.send_message(msg)


def normalize_addr(addr: str) -> str:
    return parseaddr(addr)[1].strip().lower()


def poll_once(cfg: dict, dry_run: bool = False, verbose: bool = False) -> int:
    allowed = {normalize_addr(cfg["gmail_user"])}
    for a in cfg.get("allowed_senders", []) or []:
        allowed.add(normalize_addr(a))

    M = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        M.login(cfg["gmail_user"], cfg["gmail_app_password"])
    except imaplib.IMAP4.error as e:
        sys.stderr.write(f"IMAP login failed: {e}\n")
        return 1
    try:
        M.select("INBOX")
        # Match either "/digest" or "digest:" prefixes (Gmail SEARCH SUBJECT is substring).
        typ, data = M.search(None, '(UNSEEN SUBJECT "digest")')
        if typ != "OK":
            sys.stderr.write(f"IMAP search failed: {typ}\n")
            return 1
        ids = (data[0] or b"").split()
        if verbose:
            print(f"Found {len(ids)} candidate unread messages")
        processed = 0
        for num in ids:
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = normalize_addr(msg.get("From", ""))
            subject = (msg.get("Subject") or "").strip()
            msg_id = msg.get("Message-ID")
            # Filter: must be from allowed sender AND subject starts with /digest or digest:
            if sender not in allowed:
                if verbose:
                    print(f"  skip (untrusted sender {sender}): {subject!r}")
                continue
            if not re.match(r"^\s*/?digest[:\s]", subject, flags=re.IGNORECASE):
                if verbose:
                    print(f"  skip (subject doesn't start with /digest): {subject!r}")
                continue
            if verbose:
                print(f"  process: {subject!r} from {sender}")
            try:
                result = dispatch(subject)
            except Exception as e:  # noqa: BLE001
                result = f"ERROR: command crashed: {type(e).__name__}: {e}"
            body = (
                f"Subject: {subject}\n"
                f"From: {sender}\n"
                f"---\n"
                f"{result}\n"
            )
            if dry_run:
                print(f"--- DRY RUN reply to {sender}:\n{body}\n---")
            else:
                try:
                    send_reply(cfg, sender, msg_id, subject, body)
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write(f"  reply failed: {e}\n")
                # Mark read regardless to avoid loops.
                M.store(num, "+FLAGS", "\\Seen")
            processed += 1
        if verbose:
            print(f"Processed {processed} messages")
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()
    return 0


def main(argv=None) -> int:
    _ensure_utf8_std_streams()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="Poll once and exit (default).")
    ap.add_argument("--watch", type=int, default=0,
                    help="If >0, poll every N seconds (foreground).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't send replies or mark as read; print to stdout.")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_json(CONFIG_PATH, None)
    if not cfg or "gmail_user" not in cfg:
        sys.stderr.write("config.json not found or missing gmail_user\n")
        return 1

    if args.watch > 0:
        while True:
            poll_once(cfg, dry_run=args.dry_run, verbose=args.verbose)
            time.sleep(args.watch)
    else:
        return poll_once(cfg, dry_run=args.dry_run, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
