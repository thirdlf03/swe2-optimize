> **出典**: セッション `thorn-mastodon`「セッションログ分析レポート作成」(2026-09-16)。
> データ: `~/.local/share/devin/cli/transcripts/` の SWE-2 系全85セッション
> (Max 38 / High 37 / Medium 10) の step 単位 token metrics
> (`prompt_tokens` / `cached_tokens` / `completion_tokens`) と `final_metrics`。
> 再現: `python3 tools/cache_miss.py`

# コンテキストコストと prefix キャッシュ全滅イベント

各 agent step の `prompt_tokens` は「その推論で送信されたコンテキスト全体」。
transcript に全 step 記録されているため、実課金に近いトークン流量と
キャッシュ挙動を事後計測できる。

## 観測データ

### 総量

| 指標 | 値 |
|---|---|
| セッション数 | 85 |
| 累計 prompt tokens | 261,986,999 |
| うち cached | 245,844,056 (93.8%) |
| うち uncached(新規処理分) | 16,142,943 |
| agent step 総数 | 3,093 |
| **1推論あたり平均 prompt** | **約84,700 tok** |

「1ターンの限界コスト」はセッション後半ほど高い。
コンテキストが150Kに達した後の1ステップは、キャッシュが効いても
約150K tokの再読込を伴う。後半の無駄ターン1つ≈15万tok。

### コンテキスト上限とコンパクション

- 終了時コンテキスト最大は **207,565 tok**(stylish-syringa)。
  200K前後を天井として張り付くセッションが複数ある
  (careful-amount 207K, mousy-notify 207K, speckle-energy 207K)。
- 天井到達でコンパクションが走る: speckle-energy はセッション途中で
  prompt が 205,287 → 102,998 に半減した。
- 「You are continuing work…summary」で始まるresume型セッションは16件。
  要約自体が **26〜40KB** を冒頭に占有する(kindly-theater 39.7KB 等)。

### フルprefixミス(本題)

ミスの定義: ある agent step の `cached_tokens` が直前 agent step の
`prompt_tokens` の 90%未満 = 前回送ったコンテキストがほぼ全部
キャッシュに乗らず再処理された。

| 指標 | 値 |
|---|---|
| ミスイベント総数 | 152回 |
| ミスが1回以上あったセッション | 55/85 (65%) |
| 1回あたり uncached | 中央値 62,590 tok / 平均 68,262 / 最大 198,545 |
| ミス由来 uncached 合計 | **10,375,873 tok = 全uncachedの64.3%** |

ミス時の cached は典型的に **8,000〜11,000 tok** に落ちる。
これは冒頭の静的システムプロンプト(「You are Devin」+ツール指針、
約17KB)にほぼ一致 → **静的部の直後で prefix が折れている**。

### ミスの直前トリガー(直近の非agent stepの種類)

| 直前に入ったもの | ミス数 |
|---|---|
| user メッセージ | 97 |
| system 注入(rules/metadata/notification等) | 55 |

- carnation-promotion: ミス12回のうち、subagent通知の直後5回・
  ユーザー発言の直後3回・残り4回も直近5step以内に通知または発言あり。
- **orca経由のワーカー派遣セッション(単一タスク・対話ほぼ無し)13件のうち
  11件がミス0**。対照的に対話型セッションは高率にミスが出る。
- orca関連パスを触るセッション 3.5% vs 触らない 6.2% のミス率
  → orcaの PreToolUse フック注入が主犯という仮説は棄却。

### 注入量の実測(env-hardening効果の検証)

| 項目 | 対策前 | 対策後(9/15夕〜) |
|---|---|---|
| 冒頭注入合計 | 中央値 ~21KB、最大 **112.5KB**(chip-chinchilla) | **19.4KB 固定** |
| `.claude/CLAUDE.md` import | 複数回・repo単位でも注入 | **0件** |
| `available_skills` block | 4,731〜6,415B | **2,829B**(+repoスキルで3,213B) |

「続き」型セッションの大きな冒頭は要約であり汚染ではない
(kindly-theater 60.6KB のうち 39.7KB が resume summary)。

## 根本原因(観測と推測の分離)

確実なのは「ミスは新規の非agentコンテンツ(user発言・system注入)の
直後に集中し、折れ位置は静的prefix直後(≈8-11K tok)」という点まで。

なぜ後続に追加されるはずの内容が手前のprefixを壊すのか、有力な仮説:

1. **動的ブロックの前方再描画**(有力): `<system_info>`(workspace dirs)・
   `<rules>`・`<available_skills>` はプロンプト前方の固定位置にレンダリング
   される。ユーザーターン境界やディレクトリアクセスでこれが再生成されると、
   その時点以降全てが cache miss になる。実例として northern-politician では
   セッション中に `.devin/skills/` を作成した直後 `available_skills` が
   再注入(2,829B→765Bの別版)され、その区間にミスが集中。
   ユーザーがIDEでファイルを触ると挿入される `<additional_metadata>` も同じ層。
2. **キュー滞留メッセージの中間挿入**: エージェント実行中にユーザーが
   追加入力した場合、transcript上は到着位置に記録されるが、送信側では
   別位置に splice されている可能性(未確認)。
3. **旧コンテンツのrolling eviction**: changelog に「画像がcap超過で
   毎リクエストcacheを破壊→batch evictionで修正」とある。
   同種の仕組み(古い reasoning/tool結果の置換)が他コンテンツにもあれば
   説明がつく。orca無関係・注入無しのミス78回の一部はこれか。
4. **5分TTL**: gap>15分のミスは約22件あり、これらはTTL説明で足りる。
   ただし全ミスの中央値gapは28秒で、大多数はTTLでは説明できない。

## 悪いパターン / 良いパターン

| | 形 | 結果 |
|---|---|---|
| ❌ 質問の逐次化 | ask_user_question を1問ずつ往復 | ユーザーが考えるたびに1ターン+フル再処理。carnation-promotion はミス12回・計774K tok uncached |
| ✅ 質問バッチ | 1回に最大4問 | ユーザーターン数≈ミス回数を直接削れる |
| ❌ セッション中の環境変更 | 作業中に `.devin/skills` 新設・`/add-dir` | skills/rules ブロック再描画 → 前方prefix破壊 |
| ✅ メタ作業の分離 | 設定・スキル作成は別セッション | 本編のコンテキストが安定的にキャッシュ |
| ✅ 無人ワーカー | ユーザーターン0の一発完結 | 実測でミス0が13連続 |

## 対策

### 測定の固定化(実装済み)

`tools/cache_miss.py` — ミスイベント・トリガー分布・ワーストセッションを
全transcriptsから再集計する。今後のCLIバージョンアップや注入設計変更の
効果をこの指標で追う。

### ハーネス側への設計示唆(ローカルでは実装不可、記録のみ)

- 動的ブロック(system_info/rules/additional_metadata/notifications)は
  **末尾追加**にするか、静的prefixと会話の間に置かない。
  changelogの「image evictionをbatch化してcache破壊を直した」修正と同種の問題。
- `subagent_completion_notification` は2〜13KBの個別注入。まとめて1件に
  バッチすれば破壊回数を減らせる。
- 5分TTL対策の background cache-refresh(changelog記載)があっても
  ユーザーターン駆動の破壊は防げない。

### エージェント側で緩和できる分

- 質問は `ask_user_question` の複数問機能(1-4問/回)でまとめる。
- セッション中にスキル・ルール・設定を新設しない(注入リフレッシュを誘発)。
  このrepoへのレポート作成のような「環境を変更するタスク」は本編と分ける。

## 残課題・限界

- **78/152のミスは直前stepがagent**(=直前にuser/system注入が無い)。
  直近5step内に非agentコンテンツがある例は多いが厳密な因果は未確定。
  確定にはAPI送信payloadの記録(CLI verboseモードやプロキシ)が要る。
- `cached_tokens` の意味(読み取りhit量)はAPI仕様への推測に依存。
  「ミス」の閾値90%は経験的カットオフ。
- resume要約(26-40KB)のサイズ削減余地は未分析。
- sessions.db 側との突合は未実施(transcriptのmetricsのみで完結した分析)。

## 追記(2026-09-17): 別環境での再現確認

本機の transcripts 13セッションに `tools/cache_miss.py` を適用:

| 指標 | 前回DB(85セッション) | 本機(13セッション) |
|---|---|---|
| ミスイベント | 152 | **70** |
| ミス発生セッション率 | 65% | 10/13 (77%) |
| ミス由来 uncached 合計 | 10.4M tok | **6.34M tok** |
| 1回あたり uncached 中央値 | 62,590 tok | 84,153 tok |
| トリガー: user 直後 | 97 | 40 |
| トリガー: system 注入直後 | 55 | 30 |

セッションあたりのミス密度はむしろ高い（5.4回/セッション vs 2.2回）。
ワーストは global-writer の **25回** — resume 型セッションで
ユーザー割り込み（サブエージェントキャンセルに繋がった発言、
docs/subagent-cancel.md 参照）と rules ブロックの途中再注入が
重なった個体。**別環境でも「user/system 注入直後の prefix 破壊」が
再現**し、前回の結論（注入イベント駆動のキャッシュミス）を支持する。
