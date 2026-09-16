# AGENTS.md

Devin CLI (SWE-2) のセッションログ分析で見つけた非効率・失敗パターンと、
それを機械的に防ぐ仕組み（hooks・スクリプト）を蓄積するrepo。

## 原則

- 自然言語ルールは強制力を持たない。対策は `hooks/`・`bin/` の実装を優先し、
  ルールへの記述は「分析結果の備忘」として扱う
- 主張は実測データ（`sessions.db` / `transcripts/`）に基づける。観測と推測を混ぜない
- パターンは可能なら別環境・別DBで再現確認してから「構造的原因」と呼ぶ

## 構成

```
docs/          分析レポート。新規作成は /writing-report スキルの手順・フォーマットに従う。
               主レポートは docs/<topic>.md、詳細・分割データは docs/<topic>/ に置く
hooks/         PreToolUse 等のフック。ブロック時は代替手段をメッセージに含める
bin/           フックから参照されるヘルパースクリプト
tools/         セッション分析用スクリプト（tools/README.md 参照）
setup.sh       対話型インストーラ。hooks/bin/推奨設定を ~/.config/devin に適用
.devin/skills/ writing-report（調査+執筆）/ check-report（プライバシースキャン）
```

## コマンド

```bash
python3 tools/aggregate.py    # transcripts → digest集計
python3 tools/aggregate2.py   # execコマンド分類・言語分布
# sessions.db は file:<path>?mode=ro&immutable=1 のURIで開く（WALモードは失敗することがある）
```

## やってはいけないこと

- `transcripts/`・`sessions.db` の中身をrepoにコピーしない（生ログは個人情報の塊）
- docs/ に個人情報・非公開プロジェクト名・ユーザー発言の生引用を書かない。
  **コミット前は `/check-report` スキルでスキャンする**
- README のトピック表を更新せずに新規レポートだけ置かない
- docs/ などの追加・更新を main に直接コミットしない。
  **ブランチを切って PR を作る**（公開repoのためレビュー経由にする）
