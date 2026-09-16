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
| `until/while/for ... do sleep N; done` 内 | ALLOW |
| python `while/for` ループ内の `time.sleep` | ALLOW |
| 短いsleep（<15）+ 実コマンド | ALLOW |

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
