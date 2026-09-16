> **出典**: セッション `enchanting-bead`「Devin CLI SWE-2 全セッション分析と特徴抽出」(2026-09-15)。
> `~/.local/share/devin/cli/sessions.db` のメッセージから復元。元の作業ディレクトリは空のため、本ファイルが唯一の永続コピー。

---

# SWE-2 Medium 行動特性レポート(8セッション分析)

## 対象セッション

| ファイル | 内容 | 備考 |
|---|---|---|
| amplified-zone.txt | 3Dゲーム(three.js)のパフォーマンス計測・最適化 | 最も情報量が多い(348行) |
| battle-mule.txt | ユーザー発言のみ、AGENT応答なし | 評価不能(ダイジェスト欠損) |
| chemical-longship.txt | Swift(あるパッケージ)のファイル受け渡し仕様変更 | 途中開始の短いセッション |
| held-workshop.txt | 動画ファイルの圧縮依頼 | 40行 |
| mellow-balaur.txt | CLIツールへのオプション追加 | 仕様誤読の修正過程が観察できる |
| mewing-bobble.txt | あるWebアプリの機能追加・デプロイ | サブエージェント多用 |
| quilt-thrill.txt | スクリプト改修 + リモートホストへのデプロイ | 意見求め→実装→運用まで |
| spotty-patella.txt | 画像のビルド時生成 + CIデプロイ | 最も泥臭いデバッグ(291行) |

---

## 1. 推論スタイル

**英語の一人称内心独白**で、ユーザー向け日本語出力と明確に分離。THINKは「計画→仮説→検証手段」の構造を持ち、特に**仮説駆動のデバッグ思考**が顕著。

- **先に探索、計測ポイントを決めてから動く**: `amplified-zone` 冒頭 "My first step is to explore the codebase to understand its structure, and then I'll look into measuring things like bundle size and frame rate."
- **手段のトレードオフを明示的に比較する**: "Measuring runtime performance via FPS seems like the most direct approach, but it might require setting up a headless browser with Playwright, which could be complex. Alternatively, I can focus on static analysis" (amplified-zone)。解像度を変えてGPU boundか切り分ける等、**識別実験の設計**を自分で考える。
- **「Wait,」で始まる自己修正が頻出**。自分の編集結果・前提・テスト失敗を疑って立ち止まる癖がある:
  - "Wait, the test directory is now stageRoot/'job-1'... I need to update the assertions" (chemical-longship)
  - "Wait, this file seems to have had some edits partially applied already" (mellow-balaur — 中断されたサブエージェントの残骸を検出)
  - "Wait, SWE-2 is now being billed at list price" (mellow-balaur 最終確認)
- **自分の編集ツールの出力すら疑う**: "It looks like the edit tool might have merged snippets incorrectly, as I'm seeing a duplicated `free_until` line in the output. I need to check that specific region to confirm if it's a merge artifact or an actual duplication." (mellow-balaur) — edit適用後にreadで再確認する習慣がある。
- **ルール解釈のメタ推論**を行う: オーケストレーション規約とシステムプロンプトの緊張を自覚し、"the user's always-on rule for delegation seems to implicitly ask for it, so I'll interpret that as authorization" (amplified-zone) と自分なりに決着をつける。
- **エッジケースを自発的に潰す**: 「from > to なら空リストになる→明示的にエラーにすべき」(mellow-balaur)、jobIDのパストラバーサル対策(`/`, `:` を `_` にサニタイズ、空なら `misc` へ)を指示なしで実装(chemical-longship)。

## 2. ワークフロー

**探索 → 要件の再述 → 実装(または委任)→ 検証 → 計測/目視確認 → 構造化レポート**の一貫したループ。

- **計測ファースト**: amplified-zoneでは `/tmp/perf-measure/` に Playwright スクリプトを8本以上反復作成(measure→stress→stress2→profile→profile-slam→links→prod→fps-test)。「計測→実装→再計測のサイクル」を明示。計測対象が不十分だと自分で気づく: "The current idle FPS measurement isn't stressful enough. I need to trigger a more demanding scenario" (amplified-zone)。
- **テスト・lint・build をほぼ必ず回す**: `npm run check`(typecheck+219テスト+build)、`swift test` → `swift format lint --strict` → `build.sh`(chemical-longship)、`uv run pytest` 528件 + `ruff check`(quilt-thrill)、`pnpm check/lint/fmt:check/test/build` フルセット(spotty-patella)。
- **テスト合格だけで満足しない目視・実機検証**:
  - 生成したOGP PNGを `read` で開いて描画を確認、本番URLの ogp.png をダウンロードして豆腐(文字化け)がないか目視(spotty-patella)
  - wranglerが「No updated asset files」と言ったのを鵜呑みにせず、`curl` で本番が新ハッシュのJSを返すか確認(mewing-bobble)
  - デプロイ後に `/health` + ログでWS再接続まで確認(quilt-thrill)
- **サブエージェント運用**: ユーザーの委任規約がある場面では `run_subagent` に実装を任せる(amplified-zone で計6回、mewing-bobble で計6回)。ただし**委任後に `git diff` で軽く検収する**("実装完了を受け、変更を軽く検収します" / spot-check of detector_hybrid diff, mewing-bobble)。
- **git衛生が良い**: 他人の未コミット変更と自分の変更を分離("store.ts has both my audioCtx change and unrelated modifications... commit only the clean files", amplified-zone)、`pnpm fmt` が巻き込んだ無関係ファイルの差分を確認してから放置判断(spotty-patella)、サーバー側リポの dirty 状態を pull 前に確認(quilt-thrill)。
- **破壊的・外部公開系の操作は明示的依頼を待つ**: pushについて "I need to be explicitly asked to push" (spotty-patella)、「変更はまだ uncommit なので、必要ならコミットしますか?」(mewing-bobble)。
- 作業用スクリプトは `/tmp` に隔離し、repoを汚さない。devサーバ/previewは用後に kill する後片付けの習慣あり。

## 3. エラー対応

**リトライではなく原因診断型**。エラーメッセージから一次仮説を立て、最小実験で潰す。諦めた例は8セッション中ゼロ。

- **根本原因を推定して直す**: ESM解決エラーに対し "ESM can't resolve the script from /tmp. I should probably use `createRequire` pointed at the project directory instead of moving the script." (spotty-patella)
- **ライブラリのソースまで潜る**: fonteditor-core の `init`/ArrayBuffer エラーで、試行錯誤の末に `node_modules/.pnpm/fonteditor-core@2.6.3/.../w...` のソースを `head -60` で読み仕様を確認(spotty-patella)。
- **不可解な計測結果を変数分離で追う**: 30fps張り付きに対し「ビルド起因?instancingコード起因?環境のthrottling?」を切り分け、最終的に「headlessセッション側の一時的スロットリング」と特定して再計測(amplified-zone)。
- **「不可能」の正直な報告**: ロスレス再エンコードが元より大きくなった(37→44MB)のを隠さず、「『劣化なし』かつ『元より小さい』は原理的に両立しません」と説明+選択肢提示(held-workshop)。ユーザーの厳しい再指示には即座に方針転換(CRF18で5.2MB化)。
- **lint警告の所属を切り分ける**: 大量の既存警告の中から `grep` で自分の変更箇所だけ抽出して修正(chemical-longship)。

## 4. コミュニケーション

- **日本語・簡潔・構造化**。着手前に要件を番号リストで再述する癖("要件を整理します: 1... 2... 3..." mewing-bobble;「了解です。内容を整理すると:」mellow-balaur)。
- 結果は **Before/After の表**で定量的に報告(fps/draw calls/longtask の表、圧縮サイズ等)。
- **毎ステップは喋らない**:`AGENT:` が空で `TOOLS` だけの行が非常に多い。マイルストーンごとにまとめて報告するスタイル(静かだが、やや不透明ともいえる)。
- トーンはユーザーのカジュアルさに合わせ、口語にもそのまま乗る(amplified-zone)。
- **自分の見落としを認める**: "僕のヘッドレス計測は dpr=1 だったので見逃していました(すみません)" (amplified-zone)。
- 判断をユーザーに委ねるべき分岐では `ask_user_question` や選択肢提示を使う(OGPの方向性、remote未設定時の選択肢、圧縮方式の選択肢)。
- **未来の失敗を先回りして警告**: 「`wrangler-action` で `CLOUDFLARE_API_TOKEN` secret が未設定なので失敗するはず」と事前予告+トークン作成手順を提示(spotty-patella)。

## 5. 特徴的な癖・強み・弱み

### 強み(引用付き)

1. **測定結果を額面通り受け取らない検証癖**: "Wrangler says there are no updated asset files, even though the filenames and content hashes have changed. This is odd." → 本番をcurlで実確認(mewing-bobble)。同様に「30fpsは計測環境由来の可能性」と自分の測定系そのものを疑う(amplified-zone)。
2. **自分の変更と無関係な変更の分別**: "store.ts has mixed changes – our audio context additions are mixed with unrelated, pre-existing uncommitted changes... commit only the clean files and leave store.ts uncommitted" (amplified-zone)。
3. **指示外の堅牢化を黙って入れる**: 「jobID が空/不審な値なら `misc` に逃がし、`/`・`:` は `_` にサニタイズしてパストラバーサルを防ぐ」(chemical-longship 最終報告) — 要求されてない防御的処理。
4. **要件の言い直し→実装**: 曖昧な口語依頼を要件に分解して確認してから実装(mewing-bobble)。

### 癖

- "Wait," マーカーでの立ち止まり(全セッションで頻出)
- /tmp に使い捨て検証環境を作る(perf-measure, ogp-proto)
- 完了報告に定量的な表を必ず載せる
- コミット・push・デプロイの直前に git status/log/remote を確認する儀式

### 弱み

1. **仕様の意味論を一度取り違える**: mellow-balaur で「プロモ無料」を「コスト$0で計算」と実装したが、ユーザーの意図は「推定コストはlist価格で出しつつ『今は無料』と注記」。2回の指摘を経て修正。曖昧な指示に対し、最初に解釈を確認するより実装してしまう傾向。
2. **事前見通しの甘さ**: held-workshop で「ロスレス再エンコードは元より大きくなる」ことを事前に予測・説明せず、実行してから説明(ユーザーの再確認を招いた)。amplified-zone でも dpr=1 でしか計測せず、ユーザーの実機(Retina dpr=2)の30fpsを見逃した — 計測条件の代表性感を最初に疑わなかった。
3. **サブエージェント連携の摩擦**: mellow-balaur で中断したサブエージェントの部分的な編集が残り、自身の編集と二重化("There's a duplicate line 72 leftover"等)して後始末に数ステップ消費。回収は上手いが汚す側でもあった。
4. **委任ルール適用の不一致**: ユーザーの常時オーケストレーション規約がある中、amplified-zone/mewing-bobble では「小さめの変更ですが implementer に委任します」と厳格に委任する一方、quilt-thrill・spotty-patella では同等規模の実装を自分で直接行っている。プロジェクト側ルール差の可能性もあるが、ダイジェスト上は一貫性が見えない。

## 6. トップティアモデル比での弱さ

- **曖昧仕様への upfront 確認が弱い**: mellow-balaur の誤読は、トップティアなら実装前に「$0表示か、list価格+無料注記か」を一行確認して潰せた可能性が高い。確認質問は「設計の方向性」には使うのに、「仕様の意味解釈」には使わない非対称さがある。
- **「試してから説明」型**: 結果が自明に予測できるケース(ロスレス再エンコードが膨らむ等)でもまず実行し、ユーザーの手間とターンを消費する。
- **デバッグがやや試行錯誤寄り**: spotty-patella の fonteditor-core 周りは `node -e` の当てずっぽう的な試行が4〜5連続し、最後にソースを読んで解決 — 最初にドキュメント/ソースを読む順序なら短縮できた。web_search の使用も全セッションで未観測。
- **報告の粒度**: 空 `AGENT:` ステップが多く、長時間の試行錯誤中はユーザーから見て無言時間が長い。トップティアの実装では中間進捗をもう少し細かく出すことが多い。
- **計測条件の網羅性**: dpr=1 だけで「60fps余裕」と結論し実機条件をカバーし損ねた例のように、検証マトリクスの盲点が1点残る傾向(ただし指摘後の追及は速く正確)。

**総評**: 計測・検証・git衛生・エラー診断はかなり強く、「検証のために外部世界(本番URL・生成画像・CI実行)まで見に行く」習慣はトップティア級。一方で「曖昧な仕様を確認せず実装に入る」「自明な失敗を試してから説明する」「デバッグ初期にコードリーディングより試行を優先する」点で、ミス→修正の往復が発生している。回収力が高いため致命的失敗には至っていないが、初手の精度に改善余地がある。

**補足**: battle-mule.txt はユーザー発言のみで応答がなく評価不能(ダイジェスト生成側の問題と思われる)。またダイジェストは THINK を ~400字・ツール引数を途中で切っているため、深い計画の全文やサブエージェントへの委任プロンプト内容は確認できなかった。