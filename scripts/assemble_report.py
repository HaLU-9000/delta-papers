#!/usr/bin/env python3
"""Assemble the daily digest Markdown report from fetched-papers JSON and
Claude-generated summaries JSON. Abstracts are copied verbatim so they are
never truncated.

Usage:
  assemble_report.py \
      --papers papers.json \
      --summaries summaries.json \
      --projects projects.json \
      --date 2026-04-15 \
      --out report.md

papers.json schema:
  [{"id": "...", "source": "arxiv|biorxiv|medrxiv|rss",
    "title": "...", "authors": ["..."], "published": "...",
    "categories": ["..."], "url": "...", "pdf_url": "...",
    "abstract": "...", "_projects": ["project_id", ...],
    "journal": "(optional, for rss)"}]

summaries.json schema:
  {
    "field_trend": "3-5 段落の markdown",
    "papers": {
      "<paper_id>": {
        "translation": "抄録の忠実な日本語全訳",
        "summary": "技術的要約 2-3 文"
      }
    }
  }
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def fmt_authors(authors: list[str], n: int = 5) -> str:
    if not authors:
        return "(unknown)"
    head = ", ".join(authors[:n])
    if len(authors) > n:
        head += f", … (+{len(authors) - n})"
    return head


def render_paper(p: dict, s: dict | None) -> str:
    title = p.get("title", "(no title)").strip()
    authors = fmt_authors(p.get("authors") or [])
    source = p.get("source", "?")
    journal = p.get("journal")
    source_label = f"{source}" + (f" ({journal})" if journal else "")
    published = p.get("published", "")
    cats = ", ".join(p.get("categories") or [])
    url = p.get("url", "")
    pdf_url = p.get("pdf_url", "")
    abstract = (p.get("abstract") or "").strip()

    translation = (s or {}).get("translation", "").strip()
    summary = (s or {}).get("summary", "").strip()

    links = []
    if url:
        links.append(f"[Abstract]({url})")
    if pdf_url and pdf_url != url:
        links.append(f"[PDF]({pdf_url})")
    links_line = " · ".join(links) if links else ""

    parts = [f"### {title}", ""]
    parts.append(f"**Authors**: {authors}  ")
    meta_bits = [f"**Source**: {source_label}"]
    if published:
        meta_bits.append(f"**Published**: {published}")
    if cats:
        meta_bits.append(f"**Categories**: {cats}")
    parts.append(" · ".join(meta_bits) + ("  " if links_line else ""))
    if links_line:
        parts.append(f"**Links**: {links_line}")
    parts.append("")

    if translation:
        parts.append("**日本語訳 (忠実訳)**:")
        parts.append("")
        parts.append(translation)
        parts.append("")
    if summary:
        parts.append(f"> {summary}")
        parts.append("")

    if abstract:
        parts.append("<details><summary>Original Abstract</summary>")
        parts.append("")
        parts.append(abstract)
        parts.append("")
        parts.append("</details>")
        parts.append("")

    parts.append("---")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", required=True)
    ap.add_argument("--summaries", required=True)
    ap.add_argument("--projects", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    papers = json.loads(Path(args.papers).read_text())
    summaries = json.loads(Path(args.summaries).read_text())
    projects = {p["id"]: p for p in json.loads(Path(args.projects).read_text())}

    paper_summaries = summaries.get("papers", {})
    field_trend = summaries.get("field_trend", "").strip()

    # Group by project (a paper can appear in multiple projects)
    by_project: dict[str, list[dict]] = defaultdict(list)
    for p in papers:
        for pid in p.get("_projects") or ["_unassigned"]:
            by_project[pid].append(p)

    n_total = len(papers)
    n_projects = len([pid for pid in by_project if pid in projects])
    src_counts = Counter(p.get("source", "?") for p in papers)
    rss_counts = Counter(
        p.get("journal", "(unknown)")
        for p in papers
        if p.get("source") == "rss"
    )
    multi = sum(1 for p in papers if len(p.get("_projects") or []) > 1)

    out = []
    out.append(f"# ΔPapers Digest — {args.date}")
    out.append("")
    out.append(f"{n_total} new papers across {n_projects} projects.")
    out.append("")
    out.append("---")
    out.append("")
    if field_trend:
        out.append("## 🌐 分野全体の動向")
        out.append("")
        out.append(field_trend)
        out.append("")
        out.append("---")
        out.append("")

    for pid, plist in by_project.items():
        proj = projects.get(pid)
        if proj:
            out.append(f"## 📂 Project: {proj.get('name', pid)}")
            desc = (proj.get("description") or "").strip()
            if desc:
                first_line = desc.splitlines()[0]
                out.append("")
                out.append(f"*{first_line}*")
        else:
            out.append(f"## 📂 {pid}")
        out.append("")
        for p in plist:
            s = paper_summaries.get(p.get("id", ""))
            out.append(render_paper(p, s))
            out.append("")

    out.append("## 📊 Statistics")
    out.append("")
    out.append(f"- arXiv: {src_counts.get('arxiv', 0)} papers")
    out.append(f"- bioRxiv: {src_counts.get('biorxiv', 0)} papers")
    out.append(f"- medRxiv: {src_counts.get('medrxiv', 0)} papers")
    if rss_counts:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(rss_counts.items()))
        out.append(f"- Journals (RSS): {src_counts.get('rss', 0)} papers ({detail})")
    else:
        out.append(f"- Journals (RSS): {src_counts.get('rss', 0)} papers")
    out.append(f"- Multi-project hits: {multi}")
    out.append("")
    out.append(f"*Generated by ΔPapers Digest at {datetime.now().astimezone().isoformat(timespec='seconds')}*")
    out.append("")

    Path(args.out).write_text("\n".join(out))
    print(f"Wrote {args.out} ({n_total} papers)")


if __name__ == "__main__":
    main()
