#!/usr/bin/env python3
"""Cross-platform scheduler for the ΔPapers digest skill.

Backends: launchd (darwin), cron (linux), schtasks (win32).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

LABEL_PREFIX = "com.delta-papers"
MORNING_LABEL = f"{LABEL_PREFIX}.morning-digest"
INBOX_LABEL = f"{LABEL_PREFIX}.digest-inbox"
WIN_MORNING = "DeltaPapersDigestMorning"
WIN_INBOX = "DeltaPapersDigestInbox"

CRON_MORNING_BEGIN = "# BEGIN digest-morning (managed by scheduler.py)"
CRON_MORNING_END = "# END digest-morning"
CRON_INBOX_BEGIN = "# BEGIN digest-inbox (managed by scheduler.py)"
CRON_INBOX_END = "# END digest-inbox"

HOME = str(Path.home())
SKILL_DIR = Path(HOME) / ".claude" / "skills" / "digest"
REPORTS_DIR = SKILL_DIR / "reports"
TEMPLATES_NEW = SKILL_DIR / "templates" / "launchd"
TEMPLATES_OLD = SKILL_DIR / "plist"


def backend() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "cron"
    if sys.platform == "win32":
        return "schtasks"
    raise SystemExit(f"Unsupported platform: {sys.platform}")


def ensure_reports_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_claude_bin(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("claude")
    if not found:
        raise SystemExit("error: could not locate 'claude' on PATH; pass --claude-bin PATH")
    return found


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# launchd
# ---------------------------------------------------------------------------

def _template_path(name: str) -> Path:
    new = TEMPLATES_NEW / name
    if new.exists():
        return new
    old = TEMPLATES_OLD / name
    if old.exists():
        return old
    raise SystemExit(f"error: template not found: {name}")


def _plist_path(label: str) -> Path:
    return Path(HOME) / "Library" / "LaunchAgents" / f"{label}.plist"


def _launchctl_reload(plist: Path, label: str) -> None:
    # Unload first (ignore failure), then load -w.
    run(["launchctl", "unload", str(plist)])
    r = run(["launchctl", "load", "-w", str(plist)])
    if r.returncode != 0:
        raise SystemExit(f"launchctl load failed: {r.stderr.strip() or r.stdout.strip()}")


def _launchd_install_morning(hh: int, mm: int, claude_bin: str) -> None:
    tmpl = _template_path("morning-digest.plist.template").read_text()
    out = (tmpl
           .replace("{LABEL_PREFIX}", LABEL_PREFIX)
           .replace("{HOUR}", str(hh))
           .replace("{MINUTE}", str(mm))
           .replace("{HOME}", HOME)
           .replace("{CLAUDE_BIN}", claude_bin))
    p = _plist_path(MORNING_LABEL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out)
    _launchctl_reload(p, MORNING_LABEL)
    print(f"[launchd] installed {MORNING_LABEL} at {hh:02d}:{mm:02d}")


def _launchd_install_inbox(interval_sec: int) -> None:
    tmpl = _template_path("digest-inbox.plist.template").read_text()
    out = (tmpl
           .replace("{LABEL_PREFIX}", LABEL_PREFIX)
           .replace("{INTERVAL_SEC}", str(interval_sec))
           .replace("{HOME}", HOME))
    p = _plist_path(INBOX_LABEL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out)
    _launchctl_reload(p, INBOX_LABEL)
    print(f"[launchd] installed {INBOX_LABEL} every {interval_sec}s")


def _launchd_uninstall(label: str) -> None:
    p = _plist_path(label)
    run(["launchctl", "unload", str(p)])
    if p.exists():
        p.unlink()
    print(f"[launchd] uninstalled {label}")


def _launchd_status() -> None:
    r = run(["launchctl", "list"])
    lines = r.stdout.splitlines() if r.returncode == 0 else []
    for label in (MORNING_LABEL, INBOX_LABEL):
        present = any(label in line for line in lines)
        plist_exists = _plist_path(label).exists()
        print(f"[launchd] {label}: loaded={present} plist={'yes' if plist_exists else 'no'}")


# ---------------------------------------------------------------------------
# cron
# ---------------------------------------------------------------------------

def _crontab_read() -> str:
    r = run(["crontab", "-l"])
    if r.returncode != 0:
        return ""
    return r.stdout


def _crontab_write(content: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=content, text=True,
                          capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"crontab write failed: {proc.stderr.strip()}")


def _strip_block(text: str, begin: str, end: str) -> str:
    out_lines: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line.strip() == begin:
            skipping = True
            continue
        if skipping:
            if line.strip() == end:
                skipping = False
            continue
        out_lines.append(line)
    result = "\n".join(out_lines)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def _has_block(text: str, begin: str) -> bool:
    return any(line.strip() == begin for line in text.splitlines())


def _cron_install_morning(hh: int, mm: int, claude_bin: str) -> None:
    cmd = (f"{mm} {hh} * * * /usr/bin/env CLAUDE_CODE_NONINTERACTIVE=1 "
           f"{claude_bin} -p \"/digest run\" "
           f">> $HOME/.claude/skills/digest/reports/cron.log 2>&1")
    block = f"{CRON_MORNING_BEGIN}\n{cmd}\n{CRON_MORNING_END}\n"
    current = _strip_block(_crontab_read(), CRON_MORNING_BEGIN, CRON_MORNING_END)
    if current and not current.endswith("\n"):
        current += "\n"
    _crontab_write(current + block)
    print(f"[cron] installed digest-morning at {hh:02d}:{mm:02d}")


def _cron_install_inbox(interval_sec: int) -> None:
    minutes = max(1, interval_sec // 60)
    if interval_sec < 60:
        print(f"[cron] warning: cron min granularity is 1min; "
              f"requested {interval_sec}s, using */1")
    spec = f"*/{minutes} * * * *" if minutes > 1 else "* * * * *"
    cmd = (f"{spec} /usr/bin/env python3 "
           f"$HOME/.claude/skills/digest/scripts/inbox_poll.py --once "
           f">> $HOME/.claude/skills/digest/reports/inbox.log 2>&1")
    block = f"{CRON_INBOX_BEGIN}\n{cmd}\n{CRON_INBOX_END}\n"
    current = _strip_block(_crontab_read(), CRON_INBOX_BEGIN, CRON_INBOX_END)
    if current and not current.endswith("\n"):
        current += "\n"
    _crontab_write(current + block)
    print(f"[cron] installed digest-inbox every {minutes}min")


def _cron_uninstall(begin: str, end: str, name: str) -> None:
    current = _crontab_read()
    stripped = _strip_block(current, begin, end)
    _crontab_write(stripped)
    print(f"[cron] uninstalled {name}")


def _cron_status() -> None:
    text = _crontab_read()
    print(f"[cron] digest-morning: {'present' if _has_block(text, CRON_MORNING_BEGIN) else 'absent'}")
    print(f"[cron] digest-inbox: {'present' if _has_block(text, CRON_INBOX_BEGIN) else 'absent'}")


# ---------------------------------------------------------------------------
# schtasks (Windows)
# ---------------------------------------------------------------------------

def _schtasks_install_morning(hh: int, mm: int, claude_bin: str) -> None:
    tr = (f"powershell -NoProfile -WindowStyle Hidden -Command "
          f"\"& '{claude_bin}' -p '/digest run' "
          f"*>> '$env:USERPROFILE\\.claude\\skills\\digest\\reports\\cron.log'\"")
    cmd = ["schtasks", "/Create", "/SC", "DAILY", "/ST", f"{hh:02d}:{mm:02d}",
           "/TN", WIN_MORNING, "/TR", tr, "/F"]
    r = run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"schtasks failed: {r.stderr.strip() or r.stdout.strip()}")
    print(f"[schtasks] installed {WIN_MORNING} at {hh:02d}:{mm:02d}")


def _schtasks_install_inbox(interval_sec: int) -> None:
    if interval_sec < 60:
        print(f"[schtasks] warning: min granularity 1min; requested {interval_sec}s")
    minutes = max(1, interval_sec // 60)
    tr = (f"powershell -NoProfile -WindowStyle Hidden -Command "
          f"\"& python3 '$env:USERPROFILE\\.claude\\skills\\digest\\scripts\\inbox_poll.py' --once "
          f"*>> '$env:USERPROFILE\\.claude\\skills\\digest\\reports\\inbox.log'\"")
    cmd = ["schtasks", "/Create", "/SC", "MINUTE", "/MO", str(minutes),
           "/TN", WIN_INBOX, "/TR", tr, "/F"]
    r = run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"schtasks failed: {r.stderr.strip() or r.stdout.strip()}")
    print(f"[schtasks] installed {WIN_INBOX} every {minutes}min")


def _schtasks_uninstall(name: str) -> None:
    r = run(["schtasks", "/Delete", "/TN", name, "/F"])
    if r.returncode != 0:
        print(f"[schtasks] {name} not present (or delete failed): "
              f"{r.stderr.strip() or r.stdout.strip()}")
    else:
        print(f"[schtasks] uninstalled {name}")


def _schtasks_status() -> None:
    for name in (WIN_MORNING, WIN_INBOX):
        r = run(["schtasks", "/Query", "/TN", name])
        present = r.returncode == 0
        print(f"[schtasks] {name}: {'present' if present else 'absent'}")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def cmd_install_digest(args: argparse.Namespace) -> int:
    try:
        hh, mm = args.time.split(":")
        hh_i, mm_i = int(hh), int(mm)
        if not (0 <= hh_i < 24 and 0 <= mm_i < 60):
            raise ValueError
    except ValueError:
        raise SystemExit("error: --time must be HH:MM (24h)")
    ensure_reports_dir()
    b = backend()
    if b == "launchd":
        _launchd_install_morning(hh_i, mm_i, resolve_claude_bin(args.claude_bin))
    elif b == "cron":
        _cron_install_morning(hh_i, mm_i, resolve_claude_bin(args.claude_bin))
    else:
        _schtasks_install_morning(hh_i, mm_i, resolve_claude_bin(args.claude_bin))
    return 0


def cmd_uninstall_digest(_args: argparse.Namespace) -> int:
    b = backend()
    if b == "launchd":
        _launchd_uninstall(MORNING_LABEL)
    elif b == "cron":
        _cron_uninstall(CRON_MORNING_BEGIN, CRON_MORNING_END, "digest-morning")
    else:
        _schtasks_uninstall(WIN_MORNING)
    return 0


def cmd_install_inbox(args: argparse.Namespace) -> int:
    if args.interval_sec <= 0:
        raise SystemExit("error: --interval-sec must be positive")
    ensure_reports_dir()
    b = backend()
    if b == "launchd":
        _launchd_install_inbox(args.interval_sec)
    elif b == "cron":
        _cron_install_inbox(args.interval_sec)
    else:
        _schtasks_install_inbox(args.interval_sec)
    return 0


def cmd_uninstall_inbox(_args: argparse.Namespace) -> int:
    b = backend()
    if b == "launchd":
        _launchd_uninstall(INBOX_LABEL)
    elif b == "cron":
        _cron_uninstall(CRON_INBOX_BEGIN, CRON_INBOX_END, "digest-inbox")
    else:
        _schtasks_uninstall(WIN_INBOX)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    b = backend()
    print(f"[scheduler] backend={b} platform={sys.platform}")
    if b == "launchd":
        _launchd_status()
    elif b == "cron":
        _cron_status()
    else:
        _schtasks_status()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scheduler.py",
                                description="Cross-platform scheduler for digest skill")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("install-digest", help="install morning digest job")
    s1.add_argument("--time", required=True, help="HH:MM (24h)")
    s1.add_argument("--claude-bin", default=None)
    s1.set_defaults(func=cmd_install_digest)

    s2 = sub.add_parser("uninstall-digest")
    s2.set_defaults(func=cmd_uninstall_digest)

    s3 = sub.add_parser("install-inbox")
    s3.add_argument("--interval-sec", type=int, required=True)
    s3.set_defaults(func=cmd_install_inbox)

    s4 = sub.add_parser("uninstall-inbox")
    s4.set_defaults(func=cmd_uninstall_inbox)

    s5 = sub.add_parser("status")
    s5.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
