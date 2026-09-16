> **出典**: セッション `enchanting-bead`「Devin CLI SWE-2 全セッション分析と特徴抽出」(2026-09-15)。
> `~/.local/share/devin/cli/sessions.db` のメッセージから復元。元の作業ディレクトリは空のため、本ファイルが唯一の永続コピー。

---

# SWE-2 Max 行動分析レポート

**対象**: `/tmp/swe2_analysis/max_files.txt` に列挙された 32 セッション（`/tmp/swe2_analysis/digests/*.txt`）。全 32 件を通読し、うち約 20 件を精読。

**証拠上の注意**: 各 `THINK` は先頭 ~400 文字に切り詰められた抜粋であり、推論の全貌ではない。以下の記述は「繰り返し観測されたパターン」に基づく。完了報告はエージェントの申告であり、独立検証を意味しない。

## 集計スナップショット（スコープ内 32 件）

| パターン | セッション数 | 備考 |
|---|---|---|
| ツールエラー (`TOOL_ERROR`) | 16 / 32（計 ~42 回） | `chip-chinchilla` 14 回が最多（大規模オーケストレーション） |
| `run_subagent` | 6 / 32 | `plum-sawfish`×6、`speckle-energy`×5、`ritzy-stilton`×4、`fixed-cornucopia`（3 並列）、`vagabond-tortellini`（3 並列）、`brash-antlion` |
| `todo_write` | 16 / 32 | タスク分解が必要な規模でほぼ必ず使用 |
| `ask_user_question` | 4 / 32 | `speckle-energy`×12 が突出、他は 1–3 回の限定的使用 |
| 検証コマンド（`npm run check` / `vitest` / `tsc` / `lint`） | ~23 / 32 | コードを書いたセッションではほぼ必須の通過儀礼 |
| 自己疑念マーカー（"Wait —"、"I'm realizing"、"re-evaluating" 等） | ~25 / 32 | 修辞ではなく実際に方針転換に繋がっている |

---

## 1. 推論スタイル

### 探索 → 仮説 → 実証 → 修正、の厳格なサイクル

SWE-2 Max の推論はほぼ例外なく「**まず事実を集め、仮説を立て、実験かコード検査で確かめ、矛盾したら仮説を捨てる**」という形を取る。印象的なのは「書く前に測る」癖で、`checker-relation.txt` ではテストを書く前に pitchy が E1（41Hz）を本当に検出できるかスクラッチスクリプトで実測している:

> "Let me quickly verify pitchy actually detects E1 (41Hz) before writing tests — a scratch script" (`checker-relation.txt`)

同様に `honored-ringer.txt` では「一手で即勝つ局面」をテストに埋め込むため、fixture 探索スクリプトを書き、見つかった局面を**手でトレースして検算**してから採用している（finder が報告した flip 数と自分の数えが合わず「I'm confused about the number of flips」と食い違いを潰しにいく）。

### 仮説修正は速く、証拠で即座に捨てる

`plum-sawfish.txt` が代表例。「音声が送信されない」症状に対し、VPS/ローカル経路の切り分け → 環境変数とプロセスの追跡 → 最終的に **「待っているイベント自体が API に存在しない」** という設計レベルの誤りに辿り着く:

> "**`session.output_audio.done` は Live API に存在しない**（公式明記: "GPT-Live does not emit an output-audio-done event"）。つまり現在の live 経路の区切りロジックは**そもそも来ないイベントを待っている**。" (`plum-sawfish.txt`)

途中で「委譲イベントが原因」という当初仮説を、3 者のサブエージェント検証と公式ドキュメントで覆している。「3 者一致」まで確認してから根本原因と断定する慎重さがある。

### システムレベルまで遡る診断

`boom-volcano.txt` では「dev では動くのに prod で星が動かない」から、ビルド後 CSS を直接検査し、**Lightning CSS の圧縮バグ**（`animation-timeline: scroll(root)` を `animation` ショートハンドに誤って折り畳み、宣言ごと無効化）を特定。アプリコードではなくビルドツール側の問題として longhand 書き換えで回避した。

`chip-chinchilla.txt` でも同様の切り分け:

> "The keypress event isn't reaching the page, so `window.__keys` is empty. **This indicates a test harness issue, not an application bug**" (`chip-chinchilla.txt`)

### 仕様の内部矛盾を検出する

最も再現性の高い特異行動。同一タスク仕様に含まれたピッチクラス配列のバグ（`D F D E F E C A` に対し `[2,5,2,7,5,7,0,9]` と記載。E=4 なのに 7=G が書かれている）を、**3 つの独立した worker セッション全てが同じように検出し、同じ解決策を取った**:

> "the task's array `[2,5,2,7,5,7,0,9]` is inconsistent with the note names `D F D E F E C A` (E=4, G=7); DESIGN.md and the existing `phrase.ts`/tests all confirm `[2,5,2,4,5,4,0,9]`. I'll follow the note names/DESIGN and flag it in my report." (`checker-relation.txt`)

`typhoon-sherbet.txt` と `grape-equipment.txt` も同一の推論 → 同一の「文字列表記と DESIGN.md を正とし、乖離を報告に明記」という結論。文字通りの指示遵守ではなく「意図の解釈 + 逸脱の明示」を選ぶ点が一貫している。

同種の判断として、`flaxen-tarn.txt` はタスク指定の `detector_test.ts` が vitest の include glob (`*.test.ts`) に拾われないことに気づき、規約準拠の `detector.test.ts` と命名して報告で明示した。

### 自己疑念は頻繁かつ実効的

`Wait —`/`I'm realizing`/`I'm not sure`/`re-evaluating` 系のメタ認知発話が 32 件中 ~25 件に出現し、ほぼ全てが具体的な行動変更（別コマンドでの再検査、デバッグ計装の追加、仮説の破棄）に繋がっている。`changeable-marjoram.txt`（16 回）、`three-dress.txt`（11 回）、`plum-sawfish.txt`（13 回）が特に多いが、これらはいずれも難易度の高いセッションであり、迷走ではなく収束的な再検討だった。

---

## 2. ワークフロー

### 基本形は固定的なパイプライン

```
探索（バッチ read/exec）→ 計画（todo_write）→ 実装 → 単体検証
→ デバッグ用計装 → npm run check 全門 → 自己レビュー → コミット → 報告
```

13 件ある Orca dispatched-worker セッションでは、この型がほぼテンプレ化している：

1. `DESIGN.md` + 契約ファイル + 既存テスト + tsconfig strictness を**一括バッチ read**（`TOOLS[3-6]` で並列読みが常套）
2. `node_modules` が無ければ `npm install` をバックグラウンドで回しつつコードを書く（`typhoon-sherbet`, `concise-wolfsbane`, `grape-equipment`, `hexagonal-jackfruit` で同一パターン）
3. 実装 → vitest 部分実行 → 失敗したら**一時 debug テストで内部状態を計装** → パラメータ再校正 → 全門 `npm run check` → scope 付きコミット → `worker_done`（要約は厳密に 3 文）

### コーディネーターとしてのオーケストレーション

`chip-chinchilla.txt` は最大規模の例：フェーズ分解 → 12 worker 投入 → 完了待ち → CPU レース結果の比較 → 統合 → 競合解決 → ブラウザ QA → 本番デプロイ確認まで一気通貫。worker 待機中に heartbeat を送り、自分の作業（統合用テストハーネスの準備）を並行して進める。

### 待機・監視のコストが弱点気味

ベンチマークや CI 待ちで `sleep 90`→`sleep 240`→`tail` ポーリングを繰り返す局面が複数（`honored-ringer`, `chip-chinchilla`, `sparkly-butter`）。ただし `honored-ringer` では空ログへの「suspicious」な反応から `vite-node` 下での `process.argv` の非対称性を自力で突き止めており、待機中も無駄にせず原因調査に進む性質がある。それでも総ステップ数としては過剰気味。

### テスト通過後のセルフレビューが強い

`three-dress.txt` で象徴的：

> "Build passes. Now a self-review found two real issues to fix" (`three-dress.txt`)

緑になった後のレビューで FX メッシュの raycast 横取り、oscillator の未停止、LFO 配線の音声リーク、`ScreenQuad` のシェーダー要件、インスタンスバッファ容量超過、フレーム毎 `.filter()` アロケーションという実害バグ群を自力で発見・修正した。「テストが通った＝終わり」にしない文化が安定して見られる。

---

## 3. エラー対応

**ほぼ一貫して「失敗の分類 → 変数を 1 つ変えて再試行 → 要らなければ切り分けて代替経路」**。32 件中エラー放棄は見当たらず、~42 回のツールエラー全てが診断→リトライか迂回で処理されている。

代表的な分類行動：

| エラー | 分類 | 対応 | セッション |
|---|---|---|---|
| `sed` のパイプ引用失敗 | シェル quoting | Python で書き換えに迂回 | `chip-chinchilla` |
| `--key en` が効かない | ツール仕様 | `--enter` に変更 | `chip-chinchilla` |
| 非対話 SSH で `uv` が見えない | PATH 差分 | `/home/<user>/.local/bin/uv` 絶対パス | `ritzy-stilton` |
| `npm run check` で `readonly` ナローイング失敗 | TS 型 | 明示的キャストで修正し再実行 | `grape-equipment` |
| `ty` が assert 後の `None` を警告 | 型絞り込み不足 | `assert` → 明示 `None` ガード + `self.fail` | `spiffy-radar` |
| vite-node で `argv[1]` が想定と違う | ランタイム仕様 | `bench.ts` を純粋ライブラリ化 + `bench_main.ts` 分離 | `honored-ringer` |
| ビルド時 `expect(fn)` にラベル不足 | テスト API | ラベル追加して再ビルド | `scratch-jester` |
| 複合 SSH コマンド失敗 | コマンド複雑性 | 小さい確認コマンドに分解 | `wave-suit` |

「失敗出力をちゃんと読む」姿勢も強い：`scratch-jester` では 8 件のテスト失敗に対し、truncated な出力ではなく overflow ファイルを読みにいき、座標誤り・disc 数の算術誤り・CPU ターン期待値の誤りを個別に修正。`flaxen-tarn` も `tail -40` ではなく全失敗内容を overflow ファイルから読んでいる。

一方で**不完全な検証で進む場面もある**：`chip-chinchilla` で本番スクリーンショットが空データを返し続けた際、「The screenshot returned empty data. I'm not sure if the click registered or if the tab is busy」と不確実性を明示しつつ、DOM/スナップショット状態と後続の 1 枚のスクリーンショットを証拠として採用して前進した。誠実に caveat を付けてはいるが、証拠が部分的なまま収束する判断は弱点の予兆でもある。

---

## 4. コミュニケーション

### 日本語の外面・英語の内面、という二層が全セッションで一貫

`AGENT:` のユーザー向け発話はほぼ全て簡潔な日本語の進捗報告、`THINK:` は英語。日本語は業務的だが堅すぎず、「そっちに舵を切ります」「かなり良さそう」系の軽い口調も混ざる。

### 報告は構造化・定量的

完了報告は「変更ファイル一覧 + 箇条書き + コミットハッシュ + テスト数」が定型。表の使用が多い：

- `ritzy-stilton.txt`: コスト分析を料金テーブルで提示
- `fuchsia-locust.txt`: 速度計測を p50/mean/加重平均の表で報告し、短い生成が速く見えるバイアスまで注記
- `vagabond-tortellini.txt`: 10 要件 × 6 構成の ○△× 充足マトリクス
- `fixed-cornucopia.txt`: 自分の指摘 × サブエージェント検証結果の対応表

### 不確実性は明示する

「確定値は料金計算ツールでの再計算が前提」（`vagabond-tortellini`）、「一応確認」（`stylish-syringa`）、「max 初ターンの TTFT 33.7s が大きいのはモデル切替でプロンプトキャッシュが効かなかったためと**思われます**」（`fuchsia-locust`）など、推測と事実を言語レベルで分ける。

### 質問は 1 問ずつ・推奨回答付き

`ask_user_question` は 4 セッションのみで、多用しない。使う時は `sand-pumpkin.txt` のように「まず環境の事実を自力で調べてから、1 問ずつ・各問に推奨回答を添えて」聞く。ユーザーに仕様ではなく技術面を詰めるよう修正された際は即座に「そっちに舵を切ります」と方針転換し、再び事実調査（`wrangler whoami`、`orca worktree create --help`）からやり直した。

### サブエージェント報告の扱いが丁寧

`fixed-cornucopia.txt` では 3 並列レビュー subagent の報告をそのまま鵜呑みにせず：

> "新規発見の主要点を原文で確認してから統合します" → `sed -n '55p;85p;283p;157p'` で原文突合 → "自分の指摘5件は全て原文と突き合わせて**合致**と検証され" (`fixed-cornucopia.txt`)

`plum-sawfish.txt` では実装 subagent が旧仕様のまま進んでいるのを検知し、watchdog ベースの修正仕様を送り直した。

---

## 5. 特徴的な癖・強み・弱み

### 強み

1. **横断的な事実突合**：同一 spec バグを 3 セッション独立に検出（`checker-relation`/`typhoon-sherbet`/`grape-equipment`）。DESIGN.md・既存 scaffold・タスク記述の三者を常に照合する。
2. **計装駆動のデバッグ**：推測でパラメータをいじらず、一時 debug テストで内部トレース（env/peakVel/power 時系列、timeline イベント列）を吐かせてから校正する（`flaxen-tarn`, `hexagonal-jackfruit`, `changeable-marjoram`）。
3. **層をまたぐ原因特定**：アプリ/テストハーネス/ビルドツール/CI/外部 API/シェル環境を切り分けて正しい層に修正を当てる（`chip-chinchilla`, `boom-volcano`, `ritzy-stilton`, `honored-ringer`）。
4. **緑後のセルフレビュー**：`three-dress` が典型。通過後に実害バグを量産して摘発する稀有な習慣。
5. **誠実な計測報告**：ベンチマークの分散・JIT ウォームアップ・GC ポーズを「再現しない値」として正直に記述（`rift-elderberry`, `honored-ringer`, `fuchsia-locust`）。

### 弱み

1. **ポーリング/待機の過剰**：worker や bench の完了待ちに sleep+tail を繰り返す区間が長い（`chip-chinchilla`, `honored-ringer`）。
2. **部分的証拠での収束**：スクリーンショット空データ等、ツール側が不安定な時に DOM 状態等の代替証拠で「動いた」と判断する場面（`chip-chinchilla`）。caveat は付くが検証は不完全。
3. **ルール矛盾への対処で迷いが出る**：system prompt とユーザールールの subagent 委任規約が衝突する場面で、毎回「どちらに従うか」の再推論に THINK を割いている（`hexagonal-jackfruit`, `concise-wolfsbane`, `sparkly-butter`, `understood-lightyear`, `vagabond-tortellini`）。結論は概ね正しいが無駄な思考コスト。
4. **小さいタスクでもフル探索**：`sparkly-butter`（CI フォーマット修正）程度でも規約衝突の検討から入る。タスクサイズに対し探索がやや重い傾向。

---

## 6. weaker model tier との差異（推測）

これは直接比較ではなく、観測された行動からの**期待値**である。

| 領域 | SWE-2 Max で観測 | 下位 tier で予想される差 |
|---|---|---|
| エラー持久力 | 失敗を分類し、代替経路まで自力設計（`sed`→Python、`--key`→`--enter`） | 初回失敗での停止・同じコマンドの素朴なリトライが増えるはず |
| 仕様バグ検出 | 3 セッション独立に同一矛盾を検出 | 仕様を文字通り実装し、矛盾に気づかない可能性が高い |
| ツール/アプリの切り分け | "test harness issue, not an application bug" と明確に層を分離 | ハーネス起因の失敗をアプリバグと誤診して無関係なコードを直すリスク |
| 検証文化 | テスト緑→セルフレビュー→ブラウザ/本番 QA まで多層 | 「テストが通ったので完了」で止まる確率が高い |
| オーケストレーション | 12 worker のフェーズ管理・subagent 出力の原文突合 | worker 結果の鵜呑み・統合時の競合見落としが増えるはず |
| 計測の誠実さ | 分散・ウォームアップを明記して再現性の限界を認める | 単一計測値を断定値として報告しがち |

逆に、下位 tier の方が「小タスクで過剰探索しない」「待機ループが短い」点で効率が上がる場面はある。Max の徹底さはタスクの重さに比例せず常時発動するため、軽い修正ではオーバーヘッドになり得る。

---

## 補足：親エージェントへ

- 本分析は 32 件全てを実読したが、`THINK` の切り詰めにより「推論の深さ」の評価は下限推定である。
- 引用は全て digest ファイル内の表記を検証済み（`chip-chinchilla.txt` L323/L363、`plum-sawfish.txt` L401、`three-dress.txt` L146、`changeable-marjoram.txt` L130、`dynamic-background.txt` L138、`boom-volcano.txt` L184、`checker-relation.txt` L21、`fixed-cornucopia.txt` L56 等）。
- ユーザープロンプト内のシークレット・SSH 鍵パス等は本レポートに含めていない。