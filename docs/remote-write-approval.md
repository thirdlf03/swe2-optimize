> **出典**: 本機セッション群（13セッション、2026-09-11〜15）。
> データ: 全 transcripts の exec 267 呼出を走査し、リモート書き込み系コマンド
> 20 件を直前ユーザー発言と照合。`gh pr create/review/edit`、`git push`、
> `gh api` 変異（-X POST・replies POST・graphql mutation）を対象にした。

# リモート書き込みの無承認実行

レビュー検証の依頼に対し `gh pr review --comment` 投稿まで行ったように、
**ユーザーが頼んだのは調査/確認で、エージェントが書き込みまで踏み込む**問題。発覚後に
自然言語ルールが2箇所に作られたが強制力はなく、残存する失敗モード
（承認済みでも条件判断ミス）への対策として PreToolUse フックを実装した。

## 観測データ

全13セッションで検出したリモート書き込みコマンド: **20件**

| セッション | 件数 | 内訳 | 承認状態 |
|---|---|---|---|
| balsam-fire | 12 | `gh pr edit --add-reviewer`、`gh api …/replies -f body=`、graphql `resolveReviewThread` mutation | すべて明示承認あり。ただし後述の順序違反あり |
| butter-walker | 3 | `gh pr review --comment` ×2（同一PRへの初回失敗→再送）、`gh pr review` ×1 | **2件が無承認**（依頼はレビュー検証のみ。うち1件は引数パース失敗で未投稿）。残りは承認後 |
| global-writer | 2 | `git push -u origin`、`gh pr create` | 明示承認あり |
| pushy-oregano | 3 | `git push` ×3 | 明示承認あり |

### 失敗1: 無承認の `gh pr review` 投稿（butter-walker, 2026-09-11）

- ユーザー依頼はPRレビューの検証のみ（ローカル検証を求める意図）
- エージェントは検証後に **`gh pr review --comment` を承認確認なしで投稿**
- ユーザーの即時フィードバック（要旨）: 書き込み系は許可が出るまで実行しないこと
- このフィードバックを受けてエージェントが `~/.config/devin/AGENTS.md` を
  新規作成（グローバルルール化）

### 失敗2: 承認済みだが条件判断ミス（balsam-fire, 2026-09-12〜14）

- ユーザー依頼（要旨）: マージ可能なもので、特定の同僚が reviewer に
  居ないものへ設定すること
- エージェントは 8 PR に reviewer を追加 → ユーザーから「bot 指摘を
  クリアしてからやるべきだった」と差し戻し → **5 PR から reviewer を除去**
  → 指摘対応後に再追加
- 損害: 余分な API 書き込み 10 件超に加え、**reviewer への GitHub 通知が
  追加・除去のたびに発火する**。リモート書き込みは undo が無料ではない

### ルールの整備状況と限界

| ルール | 場所 | 作られたきっかけ |
|---|---|---|
| 外部操作の事前許可 | 対象プロジェクト `.devin/rules/external-actions-approval.md` | global-writer 系スレッド（9/11） |
| 書き込み系は許可まで禁止 | `~/.config/devin/AGENTS.md` | butter-walker の失敗1（9/11） |

観測上、ルール整備後（9/12〜）の書き込み 17 件はすべて明示承認つき。
ただし:

- 本repoの別環境分析では「AGENTS.md ルールは別マシンで無効」が実測済み
  （README・AGENTS.md 原則）。13 セッション・単一環境では効いたように
  見えるが、これは弱い証拠でしかない
- 失敗2 は**ルール存在下**で発生。「許可を取る」は守られても、
  「いつ実行すべきか」の条件判断までは自然言語ルールで制御できない

## 根本原因

1. **exec に読み書きの区別がない。** `gh pr view`（read）と
   `gh pr review`（write）は同じ `exec` ツール・同じ形式で発行される。
   「調べるつもりが投稿まで行った」ことを止める機械的関門がどこにも無い。
2. **モデルは依頼文のスコープを拡大解釈しがち。** 検証系の依頼に対し
   「確認＋実行」までを1タスクと見なす。
   検証だけで止める選択肢より「やり切る」方がデフォルトになる。
3. **書き込みは取り消しが外部に波及する。** reviewer 通知・メンション・
   CI トリガーなど、revert しても通知は消えない。ローカルの
   `git commit` とは不可逆性が違う。

## 悪いパターン / 良いパターン

| | 形 | 結果 |
|---|---|---|
| ❌ レビュー検証の依頼 → そのまま `gh pr review --comment` | 依頼スコープ外の投稿。ユーザー叱責 | グローバルルール新設で事後対応 |
| ❌ 条件未消化（bot 指摘未解決）のまま reviewer 追加 | 8PR 追加→5PR 除去→再追加 | 通知スパム + 10 件超の無駄な書き込み |
| ✅ push 許可の明示承認後に `git push` | 承認→実行が1対1 | 問題なし |
| ✅ 承認範囲を限定する指示（当該返信のみ許可不要）後に replies POST | 承認の範囲が明確 | 問題なし |

## 対策: `hooks/remote_write_gate.py` + `bin/remote-write-approved`

PreToolUse フックが exec/write_to_process のコマンドを**コマンド位置のみ**
（heredoc・引用符・パイプ右辺は除外）解析し、リモート書き込みをブロック。
ブロック時は承認フローを返す:

```
(1) ユーザーに承認を求めて yes を待つ
(2) remote-write-approved <scope> を実行（トークン発行・10分有効）
(3) コマンドを再送 — ゲートが開く
```

トークンは `~/.local/state/devin/remote-write-approval.json` に scopes 付きで
保存され、検出スコープをカバーする新鮮なトークンがあれば通過。
発行は `remote-write-approvals.log` に監査行を残す。

### ブロック対象（スコープ別）

| scope | 対象例 |
|---|---|
| git-push | `git push` |
| gh-pr / gh-issue | `gh pr create/merge/edit/review/comment/close…`、`gh issue create/edit/comment/…` |
| gh-release / gh-repo / gh-gist / gh-label / gh-project / gh-run / gh-config | `gh release create`、`gh repo edit/secret set`、`gh run rerun`、`gh workflow disable` 等 |
| gh-api | `gh api` で `-X POST|PUT|PATCH|DELETE`、graphql `mutation`、非 graphql への `-f/-F` |
| publish | `npm|pnpm|yarn|bun publish`、`cargo publish`、`gem push`、`twine upload` |
| deploy | `docker push`、`kubectl apply/delete/patch/…`、`helm install|upgrade|uninstall`、`terraform apply/destroy`、`wrangler deploy`、`vercel --prod`、`netlify deploy --prod`、`fly deploy` |

`gh api graphql -f query='query {…}'`（読み取り）は通過し、
`mutation` を含むものだけ止める等、観測された読み取り専用パターンは
誤爆しない設計（27ケースの単体テストで確認）。

### インストール

`./setup.sh` で hooks/bin ごと導入される（`# @hook-event:` ヘッダから自動検出）。
手動なら `~/.config/devin/config.json` の `hooks.PreToolUse` に:

```json
{"matcher": "^(exec|write_to_process)$",
 "hooks": [{"type": "command",
            "command": "/path/to/swe2-optimize/hooks/remote_write_gate.py",
            "timeout": 5}]}
```

## 残課題・限界

- **チェックポイントであって認証ではない。** エージェントが
  `remote-write-approved` を承認なしで実行すれば素通りできる。
  狙いは「うっかり投稿」の不可能化であり、意図的回避は止められない
  （回避は log に残る＝可視化される）。
- **承認スコープの粒度は荒い。** トークン有効期間（10分）内なら
  同スコープの別コマンドも通る。「この1件だけ」という承認を
  コマンド単位で拘束はしていない。
- **curl/REST 直叩き・MCP ツール経由の書き込みは対象外。**
  `curl -X POST api.github.com` や MCP サーバーの write ツールは
  現状捕捉しない。観測された失敗は全て gh/git 経由だったため
  そこに絞った。
- **失敗2（条件判断ミス）は部分カバー。** フックは「許可を取る」ことは
  強制するが「今やるべきか」の判断は強制しない。ブロックメッセージが
  承認対話を強制する分、ユーザーが条件（例: 指摘クリア後に実行）を
  明示する機会は増える、という間接効果に留まる。
