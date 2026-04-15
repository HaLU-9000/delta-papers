---
name: digest
description: ΔPapers morning digest — generate daily research paper digests from arXiv / bioRxiv / medRxiv / Nature / Science / Cell / PNAS / Bioinformatics RSS with AI summaries and email delivery. Use for /digest setup, /digest add-project, /digest list-projects, /digest remove-project, /digest run, /digest enable-cron, /digest disable-cron.
---

# /digest — ΔPapers Morning Digest Skill

毎朝、登録した研究プロジェクトに関連する最新論文を arXiv / bioRxiv / medRxiv から取得し、Claude（あなた自身）が要約・分野動向サマリーを生成し、Markdown レポートとして保存・Gmail 配信します。

## 重要な前提

- **状態ディレクトリ**: `~/.claude/skills/digest/state/`
  - `config.json` — Gmail 認証情報・出力設定
  - `projects.json` — プロジェクト一覧（カテゴリ・キーワード・著者）
  - `seen_papers.json` — 重複防止用に通知済み論文 ID を `{project_id: [paper_id, ...]}` で保存
- **スクリプト**: `~/.claude/skills/digest/scripts/`
  - `fetch_arxiv.py` `--categories cs.AI,cs.CL --lookback-hours 30 --max-results 50 [--keywords ...] [--authors ...]`
  - `fetch_biorxiv.py` `--server biorxiv|medrxiv --categories ... --lookback-days 3 --max-results 50 [...]`
  - `fetch_rss.py` `--journals nature,science,cell,pnas,bioinformatics --lookback-days 7 --max-results 50 [--keywords ...] [--authors ...] [--feed-url <url>]` — built-in registry: `nature`, `science`, `cell`, `pnas`, `bioinformatics` (Oxford). 任意の RSS/Atom URL を `--feed-url` で追加可能（複数指定可）
  - `send_email.py` `--config <path> --markdown <path> --subject <str> [--dry-run]`
  - `assemble_report.py` `--papers <json> --summaries <json> --projects <json> --date YYYY-MM-DD --out <md>` — プログラムで Markdown を組み立てる。抄録は JSON から verbatim でコピーされるので絶対に途中で切れない。
- **レポート出力先**: `config.json` の `report_dir`（既定 `~/Documents/digest/`）に `YYYY-MM-DD.md` で保存
- **Gmail 設定**: 別ドキュメント `SETUP_GMAIL.md` 参照（App Password の取得手順）

## 引数の解釈

ユーザーが `/digest <subcommand> [args]` の形で呼び出す。`<subcommand>` を見て分岐:

- `setup` → セットアップ
- `add-project [説明文]` → プロジェクト追加（説明文なければ対話で聞く）
- `list-projects` → 一覧表示
- `remove-project <id-or-name>` → 削除
- `run [--only <id,...>] [--skip <id,...>]` → 今日のダイジェスト生成・送信 (対象プロジェクトを絞れる)
- `enable-project <id>` / `disable-project <id>` → `projects.json` の `enabled` フラグを切り替え
- `enable-cron [HH:MM]` → launchd 登録（既定 08:00）
- `disable-cron` → launchd 解除
- `enable-inbox [INTERVAL_SEC]` → 受信メール監視 launchd 登録（既定 600 秒 = 10 分）
- `disable-inbox` → 受信メール監視を解除
- 何もなし or `help` → 簡単な使い方を出力

---

## サブコマンド別の動作

### `setup`
1. ユーザーに Gmail アドレス と App Password を聞く（既に `config.json` があれば現在値を表示し、変更するか確認）
2. `config.json` を書き込み、`chmod 600` を実行
3. `report_dir` が存在しなければ作成
4. App Password の取得方法は `SETUP_GMAIL.md` を案内

### `add-project [説明文 | @<path> | <path>]`

ユーザーは以下のいずれかの方法で説明を提示できる:

1. **インラインテキスト**: `/digest add-project "深層学習でタンパク質構造予測..."`
2. **ファイル参照 (@プレフィックス)**: `/digest add-project @~/Documents/project.md`
3. **ファイルパス直接** (引数がサポート拡張子で終わる、または既存ファイルパス): `/digest add-project /path/to/desc.pdf`
4. **対話**: 引数なし → 「説明を入力してください (ファイルパスでも可)」と聞く

**サポートするファイル形式と読み込み方法**:

| 拡張子 | 読み込み方法 |
|---|---|
| `.md` / `.markdown` / `.txt` | Read ツールで直接読む |
| `.pdf` | Read ツールで直接読む (Claude Code は PDF をネイティブ対応) |
| `.docx` / `.doc` / `.rtf` / `.odt` | `Bash`: `textutil -convert txt -stdout "<path>"` で txt 化して読む (macOS 標準コマンド、追加インストール不要) |

引数の判定ルール:
- 先頭が `@` → 残り部分をパスとして展開 (`~` も展開)
- 拡張子が上記サポート対象、かつファイルが存在 → ファイル読み込み
- 引数全体が既存ファイルパス (拡張子無視) → ファイル拡張子で判定
- それ以外 → そのままインラインテキストとして扱う

ファイル読み込み時は内容全体 (見出し・箇条書き・本文すべて) を理解材料に使う。長文 (>3000 文字) でも全文読む。`docx` の場合 `textutil` が無い/失敗したら `Bash`: `command -v pandoc && pandoc -t plain "<path>"` をフォールバックとして試す。それも失敗したら `add-project` を中断してユーザーに通知。

**あなた（Claude）が直接、説明文から以下を推奨してください**（外部 API 呼び出しは不要、あなたの知識で）:

- **名前** (短い英数字 ID。説明から自動命名、ユーザー確認)
- **arXiv カテゴリ**: 3〜5 個（例: `cs.AI`, `cs.CL`, `q-bio.NC`, `stat.ML`）
- **bioRxiv/medRxiv カテゴリ**: 該当があれば 1〜3 個（例: `neuroscience`, `bioinformatics`, `genetics`）
- **ジャーナル RSS**: 該当分野で関連の高いものを `nature` / `science` / `cell` / `pnas` / `bioinformatics` から選択（複数可、ゼロ可）
- **キーワード**: 5〜10 個（論文タイトル/抄録での substring マッチに使う）
- **著者**: 3〜5 名（substring マッチに使う、姓のみで OK）
- **lookback**: arXiv hours / bioRxiv days / RSS days のデフォルト

提示後、ユーザーに確認 → 承認後に `projects.json` に追加。各プロジェクトのスキーマ:

```json
{
  "id": "llm-alignment",
  "name": "LLM Alignment Research",
  "description": "...",
  "description_source": "inline | /path/to/file.md",
  "arxiv_categories": ["cs.AI", "cs.CL", "cs.LG"],
  "arxiv_keywords": ["alignment", "RLHF", "constitutional"],
  "biorxiv_categories": [],
  "medrxiv_categories": [],
  "rss_journals": ["nature", "science"],
  "extra_rss_feeds": [],
  "authors": ["Christiano", "Bai"],
  "arxiv_lookback_hours": 30,
  "biorxiv_lookback_days": 3,
  "rss_lookback_days": 7,
  "max_papers": 30,
  "created_at": "2026-04-15T...",
  "enabled": true
}
```

### `list-projects`
`projects.json` を読んで表形式で表示（id, name, カテゴリ数, キーワード数）

### `remove-project <id-or-name>`
該当を `projects.json` から削除し、`seen_papers.json` から該当エントリも削除

### `enable-project <id-or-name>` / `disable-project <id-or-name>`
`projects.json` の該当プロジェクトの `enabled` を `true`/`false` に書き換える。`disable-project` したものは `run` で自動的に飛ばされる（`--only` で明示指定されない限り）。一時的にスキップしたいときに便利。

### `run` — ★ 毎朝の本処理 ★

1. `config.json` と `projects.json` を読む。プロジェクトがなければ「`/digest add-project` を実行してください」と出力して終了
2. **対象プロジェクトの絞り込み** (この順で適用):
   - 引数に `--only a,b,c` があれば、id/name が一致するものだけに絞る
   - 引数に `--skip x,y` があれば、それらを除外
   - `--only` 指定が無ければ、`enabled: false` のプロジェクトは自動除外 (`enabled` フィールド未設定 or `true` なら実行対象)
   - 対象ゼロなら「対象プロジェクトなし」と出力して終了
3. `seen_papers.json` を読む（無ければ `{}`）
4. 各プロジェクトについて:
   - arXiv: `fetch_arxiv.py --categories <cats> --lookback-hours <h> --max-results <n> [--keywords <kws>] [--authors <auths>]` を実行
   - bioRxiv: `biorxiv_categories` があれば `fetch_biorxiv.py --server biorxiv ...` を実行
   - medRxiv: 同様に `--server medrxiv`
   - RSS ジャーナル: `rss_journals` または `extra_rss_feeds` があれば `fetch_rss.py --journals <slugs> --lookback-days <d> --max-results <n> [--keywords ...] [--authors ...] [--feed-url <url>...]` を実行
   - 結果から `seen_papers[project_id]` に含まれる ID を除外
4. 全プロジェクトの新規論文を集約。各論文に `_projects: [project_id, ...]` を付与（複数プロジェクトにヒットした場合）
5. フェッチ結果を 1 つの `papers.json` にまとめる (各論文に `_projects` 付与)。`/tmp/digest-<date>/papers.json` 等に保存。
6. **Claude（あなた）が要約生成**:
   - 各論文 (新規分のみ) について、`config.summary_style` に従った要約テキストを生成
   - 現行の `summary_style` は「抄録の忠実な日本語全訳 + 技術的 2〜3 文要約」
   - 全体について「分野動向サマリー」: 3〜5 段落で、新トレンド・注目論文・引用パターン・分野間の連関を日本語で
   - 結果を `summaries.json` として保存: `{"field_trend": "...", "papers": {"<paper_id>": {"translation": "...", "summary": "..."}}}`
7. **Markdown 組み立ては必ず `assemble_report.py` で行う**（Claude が抄録を自分で書き写さない — 出力制限で途中切れが発生するため）。
   - `python3 scripts/assemble_report.py --papers <papers.json> --summaries <summaries.json> --projects state/projects.json --date YYYY-MM-DD --out <report_dir>/YYYY-MM-DD.md`
   - 抄録は fetch スクリプトが返した `abstract` フィールドをそのまま埋め込む。Claude が再入力・要約してはならない。
8. `send_email.py --config ... --markdown ... --subject "ΔPapers Digest YYYY-MM-DD (N papers)"` で送信
9. 送信成功なら `seen_papers[project_id]` に今回の ID 群を追加 → `seen_papers.json` を保存
10. 結果サマリー（プロジェクト数 / 論文数 / 送信先）を出力

#### Markdown レポートテンプレート (参考: `assemble_report.py` が生成する形。Claude が手書きしないこと)

```markdown
# ΔPapers Digest — {YYYY-MM-DD}

{N} new papers across {P} projects.

---

## 🌐 分野全体の動向

{Claude が生成した 3-5 段落の field trend summary}

---

## 📂 Project: {project_name}

*{description}*

### {paper_title}
**Authors**: {authors[:5] join ", "}{... if more}
**Source**: {arxiv|biorxiv|medrxiv} · **Published**: {date} · **Categories**: {cats}
**Links**: [Abstract]({url}) · [PDF]({pdf_url})

> {Claude generated 2-3 sentence Japanese summary}

<details><summary>Original Abstract</summary>

{abstract}

</details>

---

## 📊 Statistics

- arXiv: {n_arxiv} papers
- bioRxiv: {n_biorxiv} papers
- medRxiv: {n_medrxiv} papers
- Journals (RSS): {n_rss} papers ({per-journal counts})
- Multi-project hits: {n_multi}

*Generated by ΔPapers Digest at {ISO-8601 timestamp}*
```

### `enable-cron [HH:MM]`

1. 引数 `HH:MM`（既定 `08:00`）をパース
2. `~/.claude/skills/digest/plist/{LABEL_PREFIX}.morning-digest.plist` を以下のテンプレートから生成（Hour/Minute を埋め込む）
3. `~/Library/LaunchAgents/{LABEL_PREFIX}.morning-digest.plist` にコピー
4. `launchctl unload` (既存があれば) → `launchctl load -w <path>` で登録
5. 登録結果を `launchctl list | grep morning-digest` で確認
6. ログ出力先: `~/.claude/skills/digest/reports/cron.log` と `cron.err`

plist テンプレート（実際のパスは `which claude` で取得して埋め込むこと）:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL_PREFIX}.morning-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>{CLAUDE_BIN} -p "/digest run"</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>{HOUR}</integer>
    <key>Minute</key><integer>{MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key><string>{HOME}/.claude/skills/digest/reports/cron.log</string>
  <key>StandardErrorPath</key><string>{HOME}/.claude/skills/digest/reports/cron.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

### `disable-cron`
`launchctl unload ~/Library/LaunchAgents/{LABEL_PREFIX}.morning-digest.plist` を実行し、plist を削除

### `enable-inbox [INTERVAL_SEC]` / `disable-inbox`

メール経由で設定変更コマンドを受け付けるための受信ポーラを launchd に登録/解除する。

- `scripts/inbox_poll.py --once` を `INTERVAL_SEC` 秒ごとに実行 (既定 600 秒)
- 信頼済み送信者 (`config.gmail_user` または `config.allowed_senders`) からの未読メールで、件名が `/digest <cmd> [args]` (または `digest: ...`) で始まるものを処理
- 実行可能コマンドは LLM 不要のもののみ:
  - `/digest help` — 使い方を返信
  - `/digest list-projects` — プロジェクト一覧
  - `/digest enable-project <id>` / `disable-project <id>`
  - `/digest set <id> <field> <value>` — 例: `/digest set inceptis-tis arxiv_lookback_hours 168`
  - `/digest add-keyword <id> <kw>` / `remove-keyword <id> <kw>`
  - `/digest add-author <id> <author>` / `remove-author <id> <author>`
  - `/digest show-config` — App Password はマスクして返信
  - `/digest seen-clear <id>` — `seen_papers` の該当エントリを削除 (再フェッチさせる)
- 各メッセージに対して結果を Reply で返し、原メッセージは既読化
- `add-project` / `run` 等 LLM が必要な操作はメール経由不可 (Claude セッションから実行)

plist テンプレート: `plist/{LABEL_PREFIX}.digest-inbox.plist.template`。`{INTERVAL_SEC}` を埋め込み、`~/Library/LaunchAgents/{LABEL_PREFIX}.digest-inbox.plist` にコピーして `launchctl load -w` する。

---

## エラーハンドリング指針

- API 失敗 (arXiv 429 等): スクリプト側で再試行済み。それでも失敗した場合は該当ソースをスキップしてレポートに `(arXiv: fetch failed)` と注記
- Gmail 送信失敗: レポートはローカルに保存済みなので、エラー内容を表示してユーザーに通知
- `seen_papers.json` 更新は送信成功後に行う（失敗時は次回再試行で同じ論文が再掲される）

## ユーザーとの対話スタイル

- 結果は簡潔に。装飾的な絵文字は最小限
- セットアップ系コマンドは確認を取る（書き込み前に内容を表示）
- `run` は基本的に対話なしで完走させる（cron 起動を想定）
