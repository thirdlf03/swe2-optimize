# swe2-optimize

Devin CLI (SWE-2) のセッションログ分析から見つけた非効率・失敗パターンと、
それを**機械的に防ぐ仕組み**（hooks・ヘルパースクリプト）を蓄積するrepo。

自然言語のルール（「〜してください」）は守られないことがある。
各トピックは「分析（観測データ+原因）」と「強制される対策（ツール）」を
セットで管理する。

## 構成

```
docs/    分析レポート（観測データ・原因・対策の設計）
hooks/   Devin CLI hooks（PreToolUse等 — 機械的にブロック/誘導）
bin/     ヘルパースクリプト（フックの代替手段として参照される道具）
tools/   セッション分析用スクリプト（transcripts → digest集計）
.devin/skills/  writing-report（調査+執筆）/ check-report（公開前プライバシースキャン）
```

## トピック一覧

| 問題 | 分析 | 対策 |
|---|---|---|
| sleep乱打（推測時間の無条件sleepで計15.4h空費） | [docs/sleep-polling.md](docs/sleep-polling.md) | [hooks/no_blind_sleep.py](hooks/no_blind_sleep.py) + [bin/wait-for](bin/wait-for) |
| コンテキスト汚染（スキル重複登録・ルール競合・多重注入） | [docs/env-hardening.md](docs/env-hardening.md) | `read_config_from` 遮断 + スキル正本化（実施済み） |
| SWE-2の行動特性（強み/弱みの基礎データ） | [docs/swe2-characteristics.md](docs/swe2-characteristics.md) + [tier別詳細](docs/swe2-characteristics/) | —（基礎データ。サブエージェントプロファイル使い分けは試行のうえ廃止 2026-09-16） |
| コンテキストコスト（prefixキャッシュ全滅152回・10.4M tok再処理） | [docs/context-cost.md](docs/context-cost.md) | [tools/cache_miss.py](tools/cache_miss.py)（計測）＋エージェント側緩和策をdocに記載 |
| 専用ツールのバイパス（execの49%がshell経由ファイル操作。ルール注入済みでもgrep 4.7倍・find 40倍） | [docs/shell-file-ops.md](docs/shell-file-ops.md) | [hooks/no_shell_file_ops.py](hooks/no_shell_file_ops.py) |
| 対策の効果測定（hooks + orchハーネス導入前後の実測比較・副作用一覧） | [docs/tool-effectiveness.md](docs/tool-effectiveness.md) | —（検証レポート。誤爆修正など次アクションを同ファイルに列挙） |

## tools/

`sessions.db` / `transcripts/*.json` から行動データを集計するスクリプト群。
前回分析（2026-09-15, 69セッション）で使ったものを `/tmp` から救出。
新しい分析トピックを始めるときの叩き台にする。

## セットアップ（hooks / bin / 推奨設定）

```bash
./setup.sh          # 対話型。各項目を y/n で選択
./setup.sh -y       # 全て Yes (symlink インストール)
./setup.sh --copy   # コピーでインストール
./setup.sh -u       # アンインストール(ファイルとconfig登録を解除)
```

やること:

- `hooks/*` → `~/.config/devin/hooks/` に配置し、`config.json` の `hooks.<event>` に登録
  （登録情報は各ファイル先頭の `# @hook-event:` / `# @hook-matcher:` 等から自動検出）
- `bin/*` → `~/.local/bin/` に配置
- 推奨設定（`read_config_from` 遮断など）→ `config.json` に追記。変更前に `.bak.<timestamp>` を作成

手動でやる場合は `~/.config/devin/config.json` の `hooks.PreToolUse` に
`{"matcher": "...", "hooks": [{"type": "command", "command": "<hookのパス>", "timeout": 5}]}`
を追加する。プロジェクト単位なら `<repo>/.devin/hooks.v1.json` に `{"PreToolUse": [...]}` で同様に書く。

## 新しいトピックの追加手順

1. セッションログ（`~/.local/share/devin/cli/sessions.db`）で観測データを取る
   （`tools/` のスクリプトが叩き台になる）
2. `docs/<topic>.md` に「観測データ → 根本原因 → 悪いパターン/良いパターン → 対策」を書く
   （フォーマット・調査手順は `/writing-report` スキル）
   詳細データや分割レポートが必要なら `docs/<topic>/` に置く（例: `docs/swe2-characteristics/`）
3. 機械的に防げるなら `hooks/` or `bin/` に実装を置く。
   設定・プロファイル系の対策は `docs/` に適用記録を残す
4. このREADMEの表に1行追加
5. コミット・公開前に `/check-report` で個人情報・非公開情報をスキャン
