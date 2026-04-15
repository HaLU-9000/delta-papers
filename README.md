# ΔPapers - A Claude Code Skill

![image](https://github.com/HaLU-9000/delta-papers/blob/main/example)

研究プロジェクトを登録すると、関連する最新論文を各種ジャーナル、プレプリントサーバーから取得し、Claude が日本語要約と分野動向サマリーを生成して Markdown レポートとして保存・毎朝 Gmail 配信できる Claude Code skillです。

## 対応プラットフォーム

| OS | スケジューラ | 備考 |
|---|---|---|
| macOS | launchd | `~/Library/LaunchAgents/` に plist を配置 |
| Linux | cron | `crontab` コマンドが利用可能であること |
| Windows | Task Scheduler | ネイティブ。PowerShell または cmd から実行 |

スケジューラは `scripts/scheduler.py` が OS を自動検出して切り替える。docx 取り込みは macOS が `textutil`、Linux / Windows は `pandoc` が必須。

## インストール

macOS / Linux:

```bash
git clone https://github.com/HaLU-9000/delta-papers ~/.claude/skills/digest
cd ~/.claude/skills/digest
cp state/config.example.json state/config.json
chmod 600 state/config.json
```

Windows (PowerShell):

```powershell
git clone https://github.com/HaLU-9000/delta-papers $env:USERPROFILE\.claude\skills\digest
cd $env:USERPROFILE\.claude\skills\digest
Copy-Item state\config.example.json state\config.json
# chmod 相当は不要。ユーザーフォルダの ACL に依存
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

## 使用例

### 1. 初回セットアップ

```
/digest setup
```

Claude が Gmail アドレスと App Password を対話で尋ねます。App Password の取得は `SETUP_GMAIL.md` 参照。

### 2. 研究プロジェクトを登録

研究計画書 (docx / pdf / md) を渡すと、Claude が自動的に arXiv カテゴリ・キーワード・関連著者・関連ジャーナル RSS を提案します。

```
/digest add-project @~/Documents/my-grant-proposal.docx
```

インラインテキストでも可:

```
/digest add-project "Transformer-based protein structure prediction with ..."
```

追加後に確認プロンプトが出て、承認すると `state/projects.json` に保存されます。

### 3. プロジェクト一覧

```
/digest list-projects
```

### 4. 今日のダイジェストを手動実行

全プロジェクト対象:

```
/digest run
```

特定プロジェクトのみ:

```
/digest run --only inceptis-tis
/digest run --skip cell-image-foundation
```

Claude が arXiv/bioRxiv/medRxiv/主要ジャーナル RSS から新規論文を取得し、日本語要約・分野動向サマリーを生成、`~/Documents/digest/YYYY-MM-DD.md` に保存し Gmail 配信します (HTML 本文 + `.md` 添付)。

### 5. 毎朝の自動配信を有効化

```
/digest enable-cron 08:00
```

OS を自動検出して、macOS は launchd、Linux は user crontab、Windows は Task Scheduler に登録される (`scripts/scheduler.py` 経由)。いずれも毎日 08:00 に `/digest run` が走ります。解除は:

```
/digest disable-cron
```

### 6. メール経由で設定変更

外出先から Gmail で返信するだけで設定を変えられます。ポーラを有効化:

```
/digest enable-inbox 600     # 10 分ごとにチェック
```

以降、自分の Gmail から件名に `/digest <command>` を入れて送るだけ。例:

| 件名 | 効果 |
|---|---|
| `/digest list-projects` | プロジェクト一覧が返信で届く |
| `/digest disable-project inceptis-tis` | 明日の配信から除外 |
| `/digest set inceptis-tis arxiv_lookback_hours 168` | lookback を 1 週間に拡大 |
| `/digest add-keyword inceptis-tis "start codon"` | キーワード追加 |
| `/digest seen-clear inceptis-tis` | 既読リストをクリアして再取得 |
| `/digest show-config` | 設定表示 (App Password はマスク) |

解除:

```
/digest disable-inbox
```

### 7. プロジェクトを一時的に無効化

```
/digest disable-project cell-image-foundation   # 永続的にスキップ
/digest enable-project cell-image-foundation    # 復活
```

### 8. プロジェクト削除

```
/digest remove-project inceptis-tis
```

### 出力例 (メール)

件名: **ΔPapers Digest 2026-04-15 (12 papers)**

- 冒頭に Claude 生成の「分野全体の動向」(3-5 段落)
- プロジェクトごとに該当論文 (タイトル / 著者 / リンク / 日本語全訳 / 2-3 文技術要約 / 原文抄録を折り畳み表示)
- 末尾に統計 (arXiv / bioRxiv / medRxiv / RSS 別件数)
- `YYYY-MM-DD.md` 添付

---

## アーキテクチャ

- `scripts/fetch_arxiv.py` / `fetch_biorxiv.py` / `fetch_rss.py` — データソース別のフェッチャ (Python 3 stdlib のみ)
- `scripts/assemble_report.py` — 取得済み JSON + Claude 生成サマリーから Markdown を verbatim 組み立て (抄録途中切れを防ぐ)
- `scripts/send_email.py` — Material Design 風 HTML + .md 添付で Gmail 送信
- `scripts/inbox_poll.py` — IMAP で `/digest <cmd>` メールを受信し設定変更
- `scripts/scheduler.py` — OS を自動検出し launchd / cron / Task Scheduler を操作する共通 CLI
- `state/projects.json` — プロジェクト定義 (個人情報のため `.gitignore` 対象)
- `state/seen_papers.json` — 重複防止用既読 ID
- `templates/{launchd,cron,windows}/` — 各バックエンド用テンプレ (`{HOME}` `{LABEL_PREFIX}` `{INTERVAL_SEC}` 等は実行時置換)
