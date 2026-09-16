> **出典**: 2026-09-16 セッション。外部マシンの `sessions.db`
> （2026-09-15〜16 の約24h、195セッション・orcaオーケストレーション運用）を
> `tool_call_state` から全件集計。

# exec 経由のファイル操作 — 専用ツールのバイパス

Devin CLI のシステムプロンプト `# Tool Tips > ## Shell` には
「NEVER invoke `rg`, `grep`, or `find` as shell commands — use the provided
search tools instead」と明記され、**全195セッションに注入されていた**
（DBの message_nodes で確認済み）。

それでも exec の約半数が「専用ツールでできることをshellでやる」呼出だった。

## 観測データ

| 指標 | 実測値 |
|---|---|
| exec 呼出総数 | 6,914（全ツール呼出 16,598 の41.7%） |
| **専用ツール代替が可能な exec** | **3,410（49.3%）・194中184セッション(95%)** |
| `cd <dir> && <cmd>` 前置き | 2,412回・119セッション（execの35%） |
| └ `workdir` パラメータ使用 | **35回（0.5%）** |
| `grep`/`rg`（コマンド位置・ファイル検索） | 1,235回・142セッション（73%） |
| `find` | 199回・103セッション |
| `head`/`tail` でのファイル読み | 198回・80セッション |
| `cat <file>` 単体読み | 146回・92セッション |
| 参考: 専用ツール側の実績 | grep tool 298回 / find_file_by_name **5回** / read 4,093回 |

ファイル検索に限れば shell 1,434回 vs 専用ツール 303回で **shellが4.7倍**。
`find_file_by_name` に至ってはshell `find` の40倍差。

## 根本原因

### 1. モデルのデフォルト語彙はshellイディオム

`grep -rn pat src` / `find . -name` / `cat file` / `cd dir && cmd` は
モデルの事前学習上の「当たり前の書き方」。専用ツールは Tool Tips の
説明文で「推奨」されるだけで、出力に強制力がない。
**プロンプトに常時存在するルールでも破られる**——自然言語ルールの
非強制性の実測例（sleep乱打と同型）。

### 2. `cd X &&` は「永続しないcwd」への慣性対応

one-shot exec はcwdを引き継がないため、モデルは毎回 `cd` を前置きする習慣を
持つ。`workdir` パラメータは存在するが（35回＝0.5%のみ使用）、
「cdしてから実行」のイディオムの方が先に出る。
`cd <dir> &&` 1回あたり約50文字 ≈ 十数tokの無駄 ×2,412回。

### 3. 専用ツール側の実利が失われる

- `grep` tool: 4MB超ファイルのスキップ・output_mode・glob_pattern・
  コンテキスト行指定など出力制御がある。shell grep は無制御ダンプ。
- `read` tool: 行番号・ページング・**画像の視覚読み取り**対応。
  `cat`/`head` はこれらを全て捨てる（PNGをcatすれば文字化けゴミが入る）。
- `find_file_by_name`: glob高速マッチ。`find` は再帰全走査で遅い。

## 悪いパターン / 良いパターン

| | 形 | 結果 |
|---|---|---|
| ❌ | `cd /repo && grep -rn "pat" src` | cd無駄+無制御出力。両方ブロック対象 |
| ❌ | `cat package.json` | 行番号・ページングなし。read toolで済む |
| ❌ | `find . -name "*.ts"` | find_file_by_nameの方が速い |
| ✅ | `npx tsc 2>&1 \| grep -E "error"` | ストリーム絞り込みは正当（許容） |
| ✅ | `tail -f /tmp/dev.log` | readにできない追従（許容） |
| ✅ | `grep`/`find` in heredoc・`ssh host '...'` 内 | スクリプト/リモート内は許容 |

## 対策: `hooks/no_shell_file_ops.py`

exec のコマンド文字列を実行前に検査し、コマンド位置のファイル操作系を
ブロックして専用ツール名を提示する。

### 判定ルール

| パターン | 判定 | 誘導先 |
|---|---|---|
| `grep`/`egrep`/`fgrep`/`rg` がコマンド位置 | BLOCK | `grep` tool |
| `find` がコマンド位置 | BLOCK | `find_file_by_name` tool |
| `cat <file>` 単体（パイプ・リダイレクト無し） | BLOCK | `read` tool |
| `head`/`tail <file>` 単体（`-f`/`-F`除く） | BLOCK | `read` tool |
| `cd <dir> && <cmd>` が先頭コマンド | BLOCK | exec `workdir` パラメータ |
| `cmd \| grep`（パイプ絞り込み） | ALLOW | — |
| `cat f \| cmd` / `tail -f` / `cd`単体 / `(cd d && …)` / ループ内cd | ALLOW | — |
| heredoc・引用内・`$変数`・globを含む対象 | ALLOW | —（ツールが展開できないため） |

クォート・heredoc認識のセグメント分割を実装済み（`ssh host 'a; grep x'` の
引用内`;`で誤判定しない）。

### インストール

`~/.config/devin/config.json` の `hooks.PreToolUse` に追加（`./setup.sh` 経由可）:

```json
{
  "matcher": "^exec$",
  "hooks": [
    {"type": "command", "command": "/path/to/swe2-optimize/hooks/no_shell_file_ops.py", "timeout": 5}
  ]
}
```

## 残課題・限界

- **素通りできる抜け道**: `sed -n '1,50p' file`、`awk`、`less`、
  `python3 -c "open(f).read()"`、`xargs grep`、`$(grep …)` コマンド置換内、
  `cmd | while read; do grep…` 内。いずれも頻度が低い or 誤検知リスクが
  高いため現状未対応。
- **`cat a b > c`**（連結）や **`grep -q pat f && …`**（存在チェック）は
  ファイル操作だが、前者は許容・後者はブロックされる（grep toolで同等確認可）。
- `ls`（495回観測）は対象外。属性・サイズ表示に専用ツールの代替がない。
- `cd X &&` のブロックは workdir パラメータと厳密に等価（one-shotは
  cwd非永続、shell_idセッションは workdir がセッションcwdを変更）。
  `cd` 単体（永続シェルの移動）は意図的に許容。
