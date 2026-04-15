# ΔPapers - A Claude Code Skill

研究プロジェクトを登録すると、関連する最新論文を各種ジャーナル、プレプリントサーバーから取得し、Claude が日本語要約と分野動向サマリーを生成して Markdown レポートとして保存・毎朝 Gmail 配信できる Claude Code skillです。

## インストール

```bash
git clone https://github.com/HaLU-9000/delta-papers.git ~/.claude/skills/digest
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

