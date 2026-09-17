# Sleep乱打問題 — 原因分析と機械的対策

Devin CLI (SWE-2) セッションログの分析から判明した、エージェントが `sleep` を
乱打する問題の構造的原因と、hooksによる機械的防止策。

## 観測データ

### セッションDB A（マルチエージェント・オーケストレーション運用、195セッション/24h）

| 指標 | 値 |
|---|---|
| sleepを含むツール呼出 | 975回・累計約15.4時間 |
| `sleep 240-300 && task-list/inbox` | コーディネーターの完了待ちポーリング |
| `while; heartbeat; sleep 300; done` | heartbeatループ（仕様通り） |
| `sleep 20-120 && terminal read --screen` | 送信到達/承認メニューの遅延確認 |
| `sleep 2-4 && curl` | dev server起動待ち ×145 |
| `sleep 15 && cat /dev/null` | 純粋な時間潰しターン |

### セッションDB B（別マシン・orca無関係の通常開発、87セッション）

| 指標 | 値 |
|---|---|
| sleep呼出 | 265回・累計3.6時間 |
| 代表例 | `sleep 290 && ssh host "tail -20 log"`（リモートジョブ監視）等 |

**別環境でも同一パターン（240-290秒クラスタ）が再現** → ドキュメント由来ではなく
モデルのデフォルト戦略であることが証明された。

## 根本原因

### 1. `check --wait` が heartbeat により実質無効化

orcaのワーカーdispatch仕様は「5分毎にheartbeat送信」を義務化。
ところがheartbeatがinboxメッセージとして滞留し、`check --wait` が即returnする
（未ackのdeliveryがFIFO先頭でreplayされ続けるため）。

結果、コーディネーターは「worker_doneまでブロック」ができず
`sleep N && orca orchestration inbox/task-list` ポーリングに退化した。

> **設計上の問題**: liveness信号をメッセージキューに混ぜたこと。
> heartbeatはinboxメッセージではなく dispatch の属性（`last_heartbeat_at`）
> として `worker-list` 等で露出すべき。

### 2. 「条件待ち」プリミティブが届いていない

`orca terminal wait --terminal <h> --for tui-idle` という正規の待機プリミティブは
存在するが、DB Aで5回・DB Bで0回しか使われていない。
スキル文書に待機イディオムが書かれていないため、モデルが知らない。

### 3. エージェントのターン構造

「何もせず待つ」ことができない（ターンはツール呼出かユーザー出力で終わる）。
wall-clockを消費する最小表現 = `sleep` なので、モデルは
「外部の非同期処理を待つ → `sleep <見積もり> && <確認>`」をデフォルトにする。

さらに悪い点: execは長時間コマンドを自動バックグラウンド化するため、
`sleep 270 && check` は「ターン終了→別途shell出力をポーリング」となり、
sleepが「チェック実行を4.5分遅らせるだけの遅延」に成り下がっていた。

## 原則: 悪いsleepと良いsleep

| | 形 | 結果 |
|---|---|---|
| ❌ 推測待ち | `sleep 270 && check` | 見積もりは必ず外れる。早ければ遅延、遅ければ1ターン無駄 |
| ✅ 条件待ち | `until <条件>; do sleep 30; done` | 成立時に即脱出。sleepは「チェック間隔」でしかない |

`sleep` 自体は悪くない。**無条件の推測sleepが悪い。**

## 対策1: PreToolUseフック（このrepoの `hooks/no_blind_sleep.py`）

Devin CLI のhooks機構（Claude Code互換）で exec/write_to_process の
コマンド文字列を実行前に検査し、無条件sleepをブロックする。

### 判定ルール

| パターン | 判定 |
|---|---|
| `sleep N`（N≥15）ループ外 | BLOCK |
| 純粋な時間潰し（`sleep N`単体/no-op付き、N≥5） | BLOCK |
| `sleep 20m` / `sleep 1h`（単位サフィックス） | BLOCK |
| `time.sleep(300)`（python回避） | BLOCK |
| `until/while/for ... do sleep N; done` 内 | ALLOW ※ |
| python `while/for` ループ内の `time.sleep` | ALLOW ※ |
| 短いsleep（<15）+ 実コマンド | ALLOW |

※ 2026-09-16 強化: `for` ループは `break`/`exit`/`return` を含む場合のみ ALLOW。
固定リストを回る for は条件脱出しないため、break無しは盲目ポーリングと同じ
（下記「追記(2026-09-16)」参照）。

ブロック時は理由と代替手段をエージェントに返す（`decision: block` + exit 2）。
単に止めるのではなく正しい待ち方に誘導する。

### インストール

`~/.config/devin/config.json` の `hooks.PreToolUse` に追加:

```json
{
  "matcher": "^(exec|write_to_process)$",
  "hooks": [
    {
      "type": "command",
      "command": "/path/to/swe2-optimize/hooks/no_blind_sleep.py",
      "timeout": 5
    }
  ]
}
```

またはプロジェクト単位なら `.devin/hooks.v1.json` に同内容を置く。

## 対策2: 条件待機ヘルパー（`bin/wait-for`）

```bash
wait-for '<check-cmd>' [--interval 30] [--timeout 1800]
```

`<check-cmd>` が exit 0 になるまで再実行するブロッキングコマンド。
フックのブロックメッセージから参照される「正しい道具」。

```bash
# 例: worker_done到着まで待機
wait-for 'orca orchestration inbox --json | jq -e ".result.messages[] | select(.type==\"worker_done\")"'
```

## 代替イディオム（ブロック時にエージェントへ提示されるもの）

```bash
# ターミナルのアイドル（ターン終了）待ち — orca正式プリミティブ
orca terminal wait --terminal <h> --for tui-idle --timeout-ms 300000

# オーケストレーションメッセージ待ち（--types指定は必須。heartbeat対策）
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 600000 --json

# 汎用条件ループ
until <check-cmd>; do sleep 30; done

# リモートジョブ — 待機をリモート側に押し込みローカルのターンを占有しない
ssh <host> 'until <remote-check>; do sleep 30; done'

# dev server起動
npx wait-on tcp:<port>
```

## 残課題・限界

- **スクリプト内のsleepは素通り**: フックが見るのはexecのコマンド文字列のみ。
  エージェントが `.sh` を書いて中でsleepすると検知できない。
  多層防御するなら `sleep` のPATHシム（エージェント環境変数がある時だけ
  30秒超をクランプ+警告）を追加する手がある。
- **orca側の根本治療**: heartbeatをinboxメッセージから分離し
  `check --wait` を復活させるか、dispatch状態遷移（done/silent）を
  コーディネーターへのwakeイベントにする設計が本筋。
  フックは「壊れたプリミティブを正しく回避させる矯正装具」。
- **pushのカバレッジ**: 現状 "You have N orchestration messages" 注入は
  メッセージ到着にしか反応しない。「worker_doneが来ないまま静かになった
  （ハング）」を検知してwakeする仕組みがあればポーリング自体が不要になる。

## 関連データ

- sleep秒数分布の詳細・オーケストレーション統計は分析セッションの
  `sessions-analysis.html` を参照
- heartbeat送信実績: 176回（AGENTS.md改善前は28回）、ask使用: 0回

## 追記(2026-09-16): DB A 再測定と新バリアント

同一DB（195セッション/24h）を exec コマンド内のリテラル `sleep N` のみで再集計:
**439箇所・累計5.85時間**（初回の975回/15.4hはループ展開回数込みの推定実行回数。
計測方法の差であり、パターンの性質は一致）。

新たに観測したバリアント:

| 形 | 規模 | 問題 |
|---|---|---|
| `for i in $(seq 1 120); do <poll>; sleep 60; done`（**break無し**） | 4コマンド・worst計6.3h | 結果が到着しても全120回実行。sleep 90×60回=5,400s の個体も。旧フックの「ループ内sleep許容」を素通り |
| `sleep 45〜100 && cat/for /tmp/agy-*.json` | 22コマンド・13セッション | 外部エージェントCLI（`agy`、全555呼出/77セッション）の完了を固定sleepで推測待ち |
| `sleep 3 && orca orchestration check --wait …` | 2件 | `--wait` がブロッキングなのに手前でsleep。冗長 |
| `sleep 60`/`120` 単体ターン | 複数 | 純粋な時間潰し（既存フックのブロック対象） |

### 対照: 同一状況の良いパターンが1件だけ存在

| | 形 |
|---|---|
| ❌ 13セッション | `sleep 60; for f in /tmp/agy_*.json; do cat …` — 固定時間後に一括読み |
| ✅ 1セッション | `while [ ! -s /tmp/agy_x.json ] …; do sleep 15; done` — ファイル出現を条件待ち |

外部エージェント呼出は同期的なので、本来は「そのまま実行→execの
バックグラウンド化+`get_output`」か `wait-for 'test -s out.json'` で足りる。
固定sleepは「agyが遅いかも」という推測の先延ばし。

### 対応

`no_blind_sleep.py` のループ判定を強化済み:
`for ... done` 内の sleep はコマンド内に `break`/`exit`/`return` が
ある場合のみ許容（python `time.sleep` の `for` も同様）。
`while`/`until`（条件が先頭にある）と `while true`（永久デーモン=
heartbeatループ等の仕様パターン）は従来通り許容。

残る課題: `for` 内sleepを一律厳格化したため、`for f in files; do 実処理;
sleep 60; done` 型のペーシングは誤ブロックされうる（低頻度と判断）。
本当のペーシングが必要なら `wait-for --interval` 側で吸収する想定。

## 追記(2026-09-17): 第3環境での観測

本機の transcripts 13セッション（hook 未導入）での sleep 実績:

| 指標 | 値 |
|---|---|
| sleep 呼出 | **11回・累計117秒**（全て butter-walker 1セッション内） |
| 最大 | 45秒（`sleep 45; tail log; curl healthz`— Go ビルド待ちの推測待ち） |
| 240-290秒クラスタ | **再現せず** |
| フック判定 | ≥15秒の無条件sleepは 45s・15s の2件がブロック対象（計60秒） |

差の理由（推測）: 本機の長時間待ち対象はサブエージェントであり、
待機には `read_subagent` / 完了通知が使われた（ポーリング不要）。
DB A/B の sleep 乱打は「orca ワーカー/外部CLI の完了待ち」という
**通知プリミティブが無い対象への待機**で発生していた。
→ 乱打は「待ち対象に正規プリミティブがあるか」に強く依存する
ワークロード条件付きの挙動。hook の価値は「プリミティブが無い局面で
推測sleepに逃げるデフォルト」を潰す点で変わらず有効。
