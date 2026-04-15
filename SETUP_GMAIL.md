# Gmail アプリパスワード設定ガイド

digest スキルから Gmail 経由でダイジェストメールを送信するために、Gmail の **アプリパスワード** を取得します。通常の Google アカウントパスワードは使えません。

---

## 1. 前提条件: 2 段階認証を有効化

アプリパスワードは 2 段階認証が有効な Google アカウントでのみ発行できます。

- 確認・有効化: <https://myaccount.google.com/signinoptions/two-step-verification>

すでに有効な場合はこのステップをスキップして構いません。

---

## 2. アプリパスワードを生成

1. 以下の URL にアクセス:
   <https://myaccount.google.com/apppasswords>
2. アプリ名に **`ΔPapers Digest`** と入力
3. 「作成」をクリック
4. 表示された **16 文字のパスワード** をコピー
   - 4 文字 × 4 ブロックの形式で表示されます (例: `abcd efgh ijkl mnop`)
   - この画面を閉じると再表示できないので必ずコピーしてください

---

## 3. Claude Code で設定

Claude Code 内で次のコマンドを実行:

```
/digest setup
```

プロンプトに従って以下を入力します:

- **Gmail アドレス** (例: `sysbiol.grp@gmail.com`)
- **16 文字のアプリパスワード** (スペースはあってもなくても可)

---

## 4. セキュリティに関する注意

認証情報は次のパスに **平文** で保存されます:

```
~/.claude/skills/digest/state/config.json
```

パーミッションを制限しておくことを推奨します:

```bash
chmod 600 ~/.claude/skills/digest/state/config.json
```

---

## 5. アプリパスワードの取り消し

不要になった場合、または漏洩が疑われる場合:

1. <https://myaccount.google.com/apppasswords> を開く
2. `ΔPapers Digest` のエントリを探して **削除**

削除後は即座に無効化され、同じパスワードは使えなくなります。
