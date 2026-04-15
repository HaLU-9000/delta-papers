# ΔPapers Morning Digest — Claude Code Skill

毎朝、登録した研究プロジェクトに関連する最新論文を arXiv / bioRxiv / medRxiv / 各種ジャーナル RSS から取得し、Claude が日本語要約と分野動向サマリーを生成して Markdown レポートとして保存・Gmail 配信する Claude Code skill。

## インストール

```bash
git clone <this-repo> ~/.claude/skills/digest
cd ~/.claude/skills/digest
cp state/config.example.json state/config.json
chmod 600 state/config.json
```

`state/config.json` を編集して Gmail 認証情報を入れる:

```json
{
  "gmail_user": "you@gmail.com",
  "gmail_app_password": "xxxx xxxx xxxx xxxx",
  "to": "you@gmail.com",
  "report_dir": "~/Documents/digest",
  "language": "ja",
  "summary_style": "technical",
  "allowed_senders": []
}
```

App Password の取得手順は [`SETUP_GMAIL.md`](SETUP_GMAIL.md) を参照。

## 使い方

Claude Code 内で:

```
/digest setup                              # 初回設定
/digest add-project @path/to/grant.docx    # プロジェクト追加 (Claude が自動でカテゴリ提案)
/digest list-projects
/digest run [--only id] [--skip id]        # 今日のダイジェスト生成・送信
/digest enable-cron 08:00                  # 毎朝 08:00 に launchd で実行
/digest enable-inbox 600                   # メール経由でコマンドを受け付け
```

## アーキテクチャ

- `scripts/fetch_arxiv.py` / `fetch_biorxiv.py` / `fetch_rss.py` — データソース別のフェッチャ (Python 3 stdlib のみ)
- `scripts/assemble_report.py` — 取得済み JSON + Claude 生成サマリーから Markdown を verbatim 組み立て (抄録途中切れを防ぐ)
- `scripts/send_email.py` — Material Design 風 HTML + .md 添付で Gmail 送信
- `scripts/inbox_poll.py` — IMAP で `/digest <cmd>` メールを受信し設定変更
- `state/projects.json` — プロジェクト定義 (個人情報のため `.gitignore` 対象)
- `state/seen_papers.json` — 重複防止用既読 ID
- `plist/*.plist.template` — launchd テンプレ (`{HOME}` `{LABEL_PREFIX}` 等は実行時置換)

## プライバシー

`state/config.json`, `state/projects.json`, `state/seen_papers.json`, `reports/` は `.gitignore` で除外済み。これらには Gmail App Password・個人プロジェクト情報・読書履歴が含まれます。**絶対にコミットしないでください**。

## ライセンス

MIT (LICENSE 参照、必要に応じて差し替え)
