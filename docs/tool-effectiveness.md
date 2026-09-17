> **出典**: 2026-09-17 セッション。本PCの `transcripts/` 97件
> (SWE-2系・09-11〜09-17) を全件走査。hooks の判定ロジックを
> そのまま流用して「ポリシー違反」を再判定し、observation の
> `Tool rejected` で実ブロックを識別。
> データ: 導入前 67セッション(1,524 exec) / 導入後 30セッション(592 exec・約4時間)

# 対策導入の効果測定 — hooks + orch ハーネス

`no_blind_sleep.py`・`no_shell_file_ops.py`・`bin/wait-for`(swe2-optimize)と
`bin/orch` ハーネス(swe2-orca-orchestrate)の導入前後を実測比較。

導入時点(JST): no_blind_sleep = 09-16 ~22:5x(config切替の揺れあり)、
no_shell_file_ops = 09-16 23:54、orch 実運用開始 = 09-17 00:06頃。

## 観測データ

### sleep ポーリング(no_blind_sleep)

| 指標 | 導入前 (67s) | 導入後 (30s) |
|---|---|---|
| sleep呼出 / sleep引数累計 | 133回 / 1.24h | 41回 / 26.0m |
| **ポリシー違反のblind sleep実行** | **33回 / 1.13h分** | **実質0回** |
| 同上・フック有効セッションのみ | — | 0回(4回の試みは全てブロック) |
| 条件待ち(until/while/for+sleep)実行 | 2回 / 0.0m | 6回 / 13.4m(ループ内=合法) |

導入前の最悪例: 1セッションで blind sleep 12回・計37.3mの見積もり待ち
(`sleep 270 && check` 型)。導入後はこの形が実行まで至った例がゼロ。

ブロック後の挙動は全件で「条件待ちへの即時書き換え」:
- `sleep 45 && orca terminal read` → ブロック → 次stepで
  `for i in $(seq 1 20); do ... || break; done` ポーリングに置換
- `send ...; sleep 20; read` → ブロック → `orca terminal wait --for tui-idle` に置換
- 回復コストはおおむね **1ステップ/ブロック**

### shell経由ファイル操作(no_shell_file_ops)

| 指標 | 導入前 | 導入後(フック有効s) |
|---|---|---|
| 違反exec率 | 898/1524 = **58.9%** | **実質0%**(下記) |
| 実ブロック数 | — | 42回(内 fileop 38, sleep 4) |
| ブロックがあったセッション | — | ~20/30 |

導入後に違反が**実行まで至った24件は全て、フック登録前に起動済みの
セッション**(hooksはセッション開始時にconfigを読むため、稼働中
セッションには遡及しない)。登録後に起動したセッションでは実行済み違反は
境界1件(登録と同秒に起動)を除きゼロ。

### orch ハーネス

| 指標 | 実測値 |
|---|---|
| orch呼出 | 105回(clean 10, status 10, boot 8, compete 7, integrate 6, wait 4, adopt 4, patrol 3, collect 2 他) |
| 実施Run | smoke cluster + portfolio競争 ×2系統 |
| portfolio Runの成果 | 候補3本(high×2+max×1) → w-portfolio-3(max)採用 → integ merge → レビュー監査で Critical 0・install/tsc/build/dev 全再現 |
| Run所要(実時間) | Run作成→ワーカーspawn ~13分、採用→integ ~40分、review ~10分、計~2h |
| `orch wait` での完了待ち | sleepポーリングなしでイベント駆動待ちが成立 |

## 成果(観測ベース)

1. **blind sleep の実行がゼロになった**。推測待ち1回あたり平均~2分の
   無駄が、ブロック+1ステップの回復に置き換わった。
   導入前ペース(67sで1.13h)を単純換算すれば、同4時間で数十回・数十分級の
   空費を防いだ計算(ただしセッション構成が違うため過大評価注意)。
2. **exec経由ファイル操作がフック有効セッションで消えた**。
   専用ツールへの強制誘導として機能。
3. **ブロックのリダイレクトが機能している**。reason に書いた代替手段
   (workdir引数・read/grep tool・条件ループ・orca wait)へ全件で即座に
   移行し、同じ違反を繰り返すセッションはなかった。
4. **orchハーネスが E2E で完走した**: 要件→3案競争→採否→統合→監査→
   敗者cleanup まで人手は要件投入のみ。成果物は監査付きで検証再現済み。
5. **hooksとハーネスの相性**: ブロックreasonが `orca terminal wait` /
   `orchestration check --wait` を提示するため、コーディネーターの
   待機がそのまま正規プリミティブに誘導された。

## デメリット・副作用(実測)

| # | 事象 | 実測 |
|---|---|---|
| 1 | **no_blind_sleep が文字列リテラル中の `sleep N` に誤爆** | 3件: `gh pr create` のbody中の "sleep 60"、hook自身のテストfixture作成(`{"command":"sleep 60"}` をprintf)×2。いずれも正当コマンドがブロックされた |
| 2 | **専用ツールで表現できない操作のブロック** | `find . -newermt`(時間窓検索)、`rg -a`(バイナリcache走査)をブロック。当該セッションは python3/sqlite3 で代替して完遂したが +数ステップ |
| 3 | **セッション開始時ロード** | 登録済みでも稼働中セッションには効かず、24件の違反が素通り(計測上も「導入後なのに違反あり」に見える罠) |
| 4 | ブロック1回 = +1ステップのチャーン | 4時間で42ブロック ≒ 42ステップ分の往復。小さいがゼロではない |
| 5 | 並列呼出の巻き込み疑い | 1ケースで専用grep tool呼出が違反execと同stepで rejected 扱いになった可能性(未確認) |
| 6 | orch: ハーネス自体のバグを運用中に踏んだ | 注入stall(devin TUI起完了前のprompt注入で無言停止)、`clean --losers` が生きたintegratorをkill — ともに実機観測→同日修正済み |
| 7 | orch: 監督コスト | coordinatorセッションは89〜93ステップ/最長~2hの常駐。ワーカー3〜6本+integrator+reviewerで1成果物あたり~10セッション消費(並列検証の意図的トレードオフだが、トークン消費は数倍になる) |

## 根本原因の構造メモ

- 誤爆(#1)は `no_blind_sleep` が heredoc/引用符を剥がさず生テキストを
  走査するため。`no_shell_file_ops` は `strip_heredocs`+quote-aware分割を
  持つのに対し sleep側は未実装 — **実装の非対称**が原因。修正は
  「sleep判定前にheredoc/quoteを除去」を入れれば済む。
- #2 はポリシーとツール能力の非対称。「shellでしかできないfile-op」が
  存在する以上、全否定ブロックには必ず例外ケースが出る。
- #7 は設計上正当なコストだが、「コーディネーターが待機で常駐」する
  構造自体は sleepポーリング問題と同根(ターン構造上「ただ待つ」が
  できない)。patrol化・イベント駆動化が既に方向として取られている。

## 対策(デメリットへの)

| デメリット | 対策案 | 状態 |
|---|---|---|
| #1 リテラル誤爆 | no_blind_sleep に heredoc/quote 除去を追加(2026-09-17 実装)。heredocは非インタプリタ宛(cat/printf/`--body "$(cat <<EOF)"` 等)のみ剥がし、`python3 - <<EOF` は残す。引用符内sleepは `bash -c`/`ssh`/`eval`/`| sh` 等のインタプリタ宛のみカウント | **実装済み** |
| #2 能力ギャップ | no_shell_file_ops に allowlist 追加(2026-09-17 実装)。find は `-newer*`/時間述語/`-size`/`-perm`/`-exec`/`-delete`/`-prune`/`-printf`/`-regex`/`-type d` 等非glob表現述語で許可。grep系は `-a` `-U` `-P` `-z` `-o` 等の専用tool非対応フラグで許可 | **実装済み** |
| #3 遡及しない | setup.sh の完了メッセージに「既存セッションは再起動で有効化」を明記 | 未実装・ドキュメントで可 |
| #6 ハーネスバグ | 実機で発見→修正済み(注入readiness確認、loser再定義) | 済 |
| #7 監督コスト | 計測上の留意点として記録。モデル配分表で coordinator=high とし max 浪費を抑止済み | 設計済み |

## 残課題・限界

- **導入後ウィンドウが ~4時間・30セッションしかなく、その半数が
  両repoの開発/スモークセッション自体**。通常業務での定常効果は未検証。
  1〜2週間後に同指標で再測すべき。
- Devin側の不安定(空ステップ連発・応答遅延)が導入後期間と重なっており、
  **壁時計ベースの速さ比較は意図的に避けた**。本レポートの数値は
  呼出回数・sleep引数時間・ブロック回数などレイテンシ非依存の指標のみ。
- 「防げた無駄時間」は導入前ペースの外挿であり、セッション構成差
  (orch開発セッションはcd&&多用)で割引いて読むべき。
- orch の効果は n=2 Run・同一要件ジャンル(3Dポートフォリオ)のみ。
  品質向上の一般化には追加Runが必要。
- フック未適用の write_to_process / subagent 内 exec など
  素通り経路は別途棚卸しが必要。

---

# 追記 (2026-09-17 夜): 定常運用23h + 大規模Run後の再測定

前回は「導入後 ~4時間・30セッション・半数が開発スモーク」だった。
本追記は **導入後23.2h・100セッション**(内60+が本番ギャラリー制作Run
のワーカー)まで広げた再測定 + 大規模オーケストレーションで初めて
表面化した失敗パターンの記録。

計測方法変更: transcripts は ~100件でローテートされるため古いものが
消えた。今回は `sessions.db` の `tool_call_state`(全186セッション・
15,715 call の rawInput + status)を直接分類。ブロックは
`tool_call_update_json` の `Tool rejected` で識別し、**未遂(ブロック)と
実行を分離**した(前回の transcript 側カウントは未遂込みだった点に注意)。

## セッション構造の変化(観測)

| 期間 | セッション | tool calls | 内訳 |
|---|---|---|---|
| 導入前 (09-11〜16, 151.5h) | 96 | 6,866 | ほぼ対話型 + 初期orcaワーカー19 |
| 導入後 (09-16 23:54〜, 23.2h) | 100 | 8,849 | 対話19(内spawn失敗stub等数件) + coordinator9 + ワーカー62 + integ/review10 |

- 09-17 単日で 98セッション・8,795 call。従来の最多日(09-14 の2,448 call)の **3.6倍**。
- `run_subagent` は導入前91回 → 導入後 **0回**。組込みサブエージェントは
  orca ワーカーに完全に置き換わった。
- ワーカー実績: 所要時間 median 49分(mean 59分・最大174分)、
  tool calls median 92。

## hooks 再測定(導入後全100セッション)

| 指標 | 実測 |
|---|---|
| blind sleep **実行** | **0回**(未遂12回は全てブロック) |
| fileop違反 **実行** | 29回(下記fork由来28 + 境界1) → 通常セッションでは実質0 |
| fileop ブロック | **296回 / 90セッション**(1セッションあたり平均~3.3回) |
| sleep ブロック | 12回 |
| ブロック後の回復 | 全件 1ステップで専用ツール/workdir引数に置換(transcript確認) |

### 新規の構造的発見: fork は親セッションのhookスナップショットを継承する

`kind-pangolin`(00:30 開始・hook登録済み期間)で `cd &&` 28回が
**ブロックされず実行**された。一方同セッションでは `sleep 20` が正しく
ブロックされている。親 `melodic-scent` は 23:19 開始 =
sleep hook(22:47)登録後・fileop hook(23:54)登録前。

> fork で作られたセッションは、作成時点の config でなく
> **親セッション作成時点のhookセットを引き継ぐ**。
> 「既存セッションに遡及しない」だけでなく、**古い親からforkした
> 新セッションにも新hookは届かない**。
> (推測: 親子リンクはDB上確認できず、時系列とブロック挙動からの推定)

その他の素通り経路棚卸し(post期): `write_to_process` 2回のみ、
run_subagent 0回 — 現状の迂回面は小さい。

## 大規模Runの観測 (3Dギャラリー制作Run, 03:21〜19:20)

要件投入 → 作品20本並列ワーカー ×2波 + 調査/ドシエ/ペルソナ/審査員4人/
集約/統合/監査まで、人手は要件投入と途中の対話質問のみ。

**良かった点(観測)**

- コーディネーターの待機が完全にイベント駆動化: `orch wait` 19回・
  `orchestration check --wait` 23回 + `get_output` ブロッキング読み。
  sleepポーリングなしで16hパイプラインを回した。
- ワーカーの自己検証が orca ブラウザ前提の形に定着:
  `orca eval` 328回(ページ内JSで物理シミュレーション数百tickの
  ストレステスト等)、`orca screenshot`+画像read 112回、
  `orca console` でコンソールエラー点検、typecheck/build 後に
  commit → `orchestration send` で進捗/worker_done 報告169回。
- コーディネーター側も検証を握る: 統合後に自分で typecheck/build、
  全40ルートのスクリーンショット sweep、採点表の算術検証スクリプト、
  「コミット忘れ」「誤spec」などワーカー異常を検出→処置できていた。
- `worker_done` → adopt → integrate → reviewer監査 → main merge の
  全工程が hooks と両立して完走。成果物は Cloudflare に deploy 済み。

**新しく表面化した失敗パターン(実測)**

| # | 事象 | 実測 |
|---|---|---|
| A | coordinator が書いた bash ループの `declare -A` が macOS bash 3.2 で不発 → task↔model マップ崩壊 | w21 に作品40のspecが混入(誤作品を構築・respawn必要) + spawn storm |
| B | 短間隔連続 spawn → `worker-start failed: null` 多発 | 失敗ごとに worktree/branch が残留し 17 stale worktrees・62 stale branches。手動清掃が必要に |
| C | `ORCH_ALLOW` がバックグラウンドシェルに引き継がれず max モデル spawn が拒否 | 3ワーカー + w40 が連続失敗(4回リトライで stale branch×4) |
| D | `orchestration check --wait` が未ackメッセージを再配信し続ける | coordinator が ~4ステップを `--ack` 発見に消費 |
| E | ワーカーのコミット忘れ | 2件(scored.md 群、AUDIT.md)。coordinator が代行コミット |
| F | spawn 直後に動かない stub/ゾンビセッション | `volcano-slayer`(coordinator spawn・18msg・0 call)、`plural-money`(pre期・732min・0 call) |
| G | ブロック往復の定常コスト | 296 fileop + 12 sleep ブロック ≒ 308ステップ/23h。セッションごとに hook が教え直す構造(ワーカー量産で線形に増える) |
| H | coordinator モデル配分の揺れ | ガイドラインは coordinator=high だが実運用の2セッションは swe-2-max で起動 |

## 根本原因メモ(追記分)

- Aは「コーディネーターの shell 依存スクリプト」という実行基盤の脆さ。
  bash 3.2 縛りは macOS 固有だが、**map構造を shell で持つ設計自体**が
  spec混入の遠因。ハーネス側で task→model 割当を持てば防げる。
- B/Cは spawn が「失敗しても副作用(worktree)を残し、エラーも
  `failed: null` と情報量ゼロ」という API 設計由来。レート制御・
  冪等性・stale掃除は harness 責務にすべき。
- Dは ack が「存在するが文書化・自動化されていない」プリミティブ欠落。
- Gは強制力のある仕組み(hook)と学習がセッション単位でリセットされる
  構造の衝突。**ルールを worker spec/playbook にも書けば初手から
  避けられる**はず(未検証)。

## 対策(追記分)

| 事象 | 対策案 | 状態 |
|---|---|---|
| G 毎セッション教え直し | orch のワーカーspecテンプレに「専用ツール使用・`cd DIR&&`禁止(workdir引数を使え)」を定型句として注入。ブロック数を /10 級に減らせる見込み | 未実装・効果は次回Runで測定 |
| B spawn storm + 残骸 | orch spawn に直列化+rate limitと、失敗時の stale worktree/branch 自動回収を入れる | 未実装 |
| A bash 3.2 | playbook/coordinator向け注意に「macOS bash 3.2・連想配列不可。mapは spec ファイルか python で」と明記 | 未実装・文書で可 |
| C ORCH_ALLOW 喪失 | spawn 呼出を env 直書きでなく orch 側でモデル許可を保持する設計に | 未実装 |
| D ack 未配送 | orchestration スキル/playbook に ack 手順を記載、または check --wait の auto-ack オプション | 未実装 |
| E コミット忘れ | worker spec に「worker_done 前に全成果物を commit」を定型句化 + `orch adopt` が dirty worktree を検出警告 | 未実装 |
| F ゾンビ | `orch status` が「spawn済み・0 tool calls・X分経過」を異常として報告 | 未実装 |
| fork のhook継承 | fork セッション作成時に hook を再評価するよう CLI 側に期待(こちらでは制御不可)。観測記録のみ | 記録のみ |

## 残課題・限界(追記分)

- transcripts が ~1日でローテートするため、今後の再測は
  `tool_call_state` 起点が必須。reasoning/THINK 分析は直近分しか不能。
- 成功側の証拠は「coordinator 自己検証」ベース。作品の実品質は
  ユーザー評価を経ていない(採点レビューは行われた)。
- n=1 大規模Run・同一ジャンル(3D Webギャラリー)。パターンA〜Hの
  再現性は次回Run以降で確認要。
- トークンコストは DB に値なし。calls ベースの相対量のみ:
  導入前 ~45 calls/h → 導入後 ~381 calls/h(**時間あたり ~8.4倍**。
  ワーカー並列稼働による密度増)。
