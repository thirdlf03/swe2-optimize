> **出典**: セッション `enchanting-bead`「Devin CLI SWE-2 全セッション分析と特徴抽出」(2026-09-15)。
> `~/.local/share/devin/cli/sessions.db` のメッセージから復元。元の作業ディレクトリは空のため、本ファイルが唯一の永続コピー。

---

# SWE-2 High セッション分析レポート（29セッション対象）

## 対象データ

`/tmp/swe2_analysis/high_files.txt` の29セッションを精査。内訳: 大規模セッション（platinum-mustard 766行、three-conga 618行、mousy-notify 373行、careful-amount 391行、purple-restaurant 289行、carnation-promotion 386行）を中心に27セッションを実読。タスク領域はインフラ構築・OSS開発・音声処理評価・システム管理・クリエイティブまで多岐。

## 1. 推論スタイル

**THINK は英語、応答は日本語。** 内部推論は英語の一人称思考（"I need to...", "Wait, ...", "I'm confused why..."）で、報告はユーザーのカジュアルな日本語に合わせる。

- **仮説駆動のボトムアップ推論**: 「結論→検証」のトップダウン型ではなく、観測→仮説→実験のサイクルを回す。three-conga でコスト算出が空になる原因を「マイクロ秒のタイムスタンプ → /var/folders のパス → `json.dumps` の空白区切り」と仮説を連鎖的に潰し、最終的に `separators=(",", ":")` で解決した。
- **自己修正マーカー "Wait," が頻出**: THINK 内で "Wait" / "confused" / "odd" 系の立ち止まりが全29ファイルで88箇所。例: `THINK: Wait, the commit included node_modules? That's way too much.`（platinum-mustard）。失敗をそのまま流さず立ち止まって原因を考える癖がある。
- **選択肢の比較検討を明示**: "I'm leaning towards X because..." / "I'm considering whether to..." という形でトレードオフを考えてから動く。platinum-mustard では linter カテゴリの選択を「correctness は error、suspicious/perf は warning、style は formatter と競合するので外す」と根拠付きで決定。
- **検証不能な事実は推測しない**: festive-fiction で「自分の tok/s は測れるか」と聞かれ、最初「内側から見る手段はない」と答えつつ、sessions.db を掘って `ttft_ms`/`tokens_per_sec` の実測値を発見し「推定不要で正確な値が取れます」と訂正。

## 2. ワークフロー

**探索→実装→実機検証のサイクルを厳格に守る。** 「動くはず」ではなく必ず実測で締める。

- **実測主義**: platinum-mustard では lint/format/build/dev サーバ起動（`localhost:3100 が 200、368ms で Ready`）まで全部検証。careful-amount では worktree を実際に4回作成（test-setup〜4）して setup/archive フックの e2e を通した。purple-restaurant では本番サーバにデプロイ後、DB の `item_updated` を偽装して実際に再通知が飛ぶかまで検証。
- **バックグラウンド並列化**: mousy-notify で評価マトリクスを `for spec in ...` の裏実行に回しつつ「その間に新規関数のテストを書きます」と待ち時間を有効利用。local-desert では `sleep 285 && ssh ...` でリモートバッチを長期ポーリング監視。
- **テスト実行**: pytest / swift test / golangci-lint / oxlint / gofmt / `node --check` / `npx tsc --noEmit` など環境に応じた検証を毎回走らせる。surf-picture ではサブエージェント成果物の diff を自分でレビューし、テスト失敗を `git stash` で HEAD と切り分けて「負荷依存のフレーク、退行ではない」と証明した。
- **git 操作は丁寧だが事故もある**: コミットは conventional 形式、PR はテンプレート準拠。ただし platinum-mustard で `git add -A` が `.gitignore` 無しのブランチで node_modules まで吸い込む事故を起こし、即 `reset --soft` で修復してユーザーに正直に報告している。
- **後片付けの習慣**: 実験用 worktree・ダミーファイル・壊れた依存（penn/mt3-infer）・ビルド成果物を能動的に掃除する。

## 3. エラー対応

**ほぼ諦めない。まず原因診断→代替経路、という型。** 23箇所の TOOL_ERROR 全てで即リトライではなく診断を挟んでいる。

- **エラー文脈を読んで方針転換**: ultra-cotija で `brew uninstall --cask ollama` 失敗 → `brew list` で formula だと特定 → `brew uninstall ollama` に切替。purple-restaurant で CGO クロスコンパイル失敗 → `CGO_ENABLED=0`（modernc sqlite は pure Go と根拠付き）。
- **権限の壁は代替手段**: root 所有アプリ削除で `mv` が弾かれる → `osascript` の `do shell script ... with administrator privileges` で GUI 認証ダイアログをユーザーに出させる（dedicated-basketball）。passwordless sudo 無しと分かると `sudo rm` コマンドを渡してユーザーに委ねる（ultra-cotija）。
- **外部ツールの quirk を実験で特定**: mousy-notify で torchcrepe の periodicity が -inf → ソースを grep して `fmin=31` が CREPE の bin 起点 32.7Hz 未満で負 index → 全 bin マスクと特定。three-conga で ccusage が空白入り JSON を拾えないと文字列マッチ仮説で特定。
- **スパイクの見切り**: mousy-notify で mt3-infer が transformers 4.x/5.x の狭い互換窓にハマらないと判明 → 5バージョン試した末「要パッチ、導入不可」と判断して venv を元に戻す。撤退判断もできる。
- **ユーザーの環境差分も追う**: three-conga で自分の環境では動いた `--as` がユーザー側で失敗 → PATH 非依存のフォールバック+キャッシュ+警告を実装。

## 4. コミュニケーション

- **日本語・丁寧カジュアル**: 「〜ですね」「やります」「いけます」。ユーザーの「w」や口語にも柔軟に乗るが、内容は実務的。
- **構造化報告**: `## やったこと` `## 変更内容` `## 結果` 等の見出し+表形式が定型。進行中は「コミットして push します」「検証します」の一行ステータスを挟む。
- **正直さを明示する口癖**: 「正直な見解を述べます」「率直に言って」「正直に精査します」（platinum-mustard で5回）。ユーザーが構成の評価を求めると「正直な評価をすると：**この構成はかなり良い**です。…一方で、気をつける点もいくつかあります」と良し悪し両面を返す（careful-amount）。
- **未検証の明示**: 「dev サーバーの起動確認だけやっておきます（未検証だった項目）」「ブラウザ実機のピンチは未検証」のように、確認した事実と未確認を分けて報告する。
- **認識ずれを言語化して確認**: platinum-mustard で assignee の意味が食い違った時、「ここで認識が分かれるので確認させてください。2通りあり得ます：A)…B)…」と解釈を並べて選ばせた。

## 5. 特徴的な癖・強み・弱み

**強み:**

- **調査の証拠主義**: purple-restaurant で「既存タグにリリースノートが付くと通知が来ない」問題を、GitHub の releases.atom を複数リポジトリで curl し「裸タグでもエントリが出る（`v2.56.0-rc0` は API 404 なのに feed に出る）」と実証してから修正設計。実サーバのログ・DB も証拠として集めた。
- **評価の科学性**: mousy-notify で `shifts=1` の +0.019 改善に「実はランダム位相の可能性（平均化の恩恵は shifts≥2 が必要）」と自分の結果を疑い、shifts=2 で再計測。`beat_mult_search` の stem 悪化もスコアバイアスまで掘って「識別不能」を確認し安全側（×2-only）に倒した。
- **曖昧指示の解釈力**: 曖昧な口語の症状報告（carnation-promotion）を「画面遷移時のカクつき」の話だと特定し、React のシーンツリー再マウントによる最大133msロングタスクを計測→構造変更で 16.8ms に改善。

**弱み・癖:**

- **サブエージェント方針がセッション間で不整合**: CLAUDE.md の委任規約 vs システムプロンプト「明示的に頼まれるまで使わない」の衝突を毎回 THINK で再検討し、結論が揺れる。three-conga/ultra-cotija/mousy-notify では「自分でやる」、surf-picture/careful-amount/carnation-promotion では「CLAUDE.md 優先で委任」、lavender-scion では「委任すると言いつつ実際は自分で `ls`」と不定。
- **質問形式が揺れる**: 同じインタビュー形式の指示プロンプトに対し、carnation-promotion は `ask_user_question` ツール17連発、platinum-mustard は `**Q2. …**` 番号付き質問+「推奨:」をテキストで返す別方式。
- **時々やりすぎる**: three-conga の `devin -p` サブプロセス計測は289秒ブロック。local-desert は ssh ポーリングが数十ターン続く（ただし意図的な監視）。platinum-mustard の `git add -A` 事故のように、広い対象への一括操作で範囲外を巻き込む場面も稀にある。

**引用例:**

1. `THINK: I think I just accidentally staged node_modules and build artifacts because the current branch was cut from main, which lacks the root .gitignore... I need to check the git log`（platinum-mustard）— 事故の自己検出と即修復。
2. `AGENT: 原因特定: json.dumps のデフォルトが "key": value(空白入り)を出力し、ccusage の行検出(おそらく "type":"assistant" の文字列マッチ)を通らない。区切りを詰めます。`（three-conga）— 外部ツールの実装を推測で断定しつつ実験で裏付け。
3. `AGENT: その症状も同じ原因の可能性が高いです — 無音フレームが流れ続けるたびにエコーガードが立ち直るので、マイクを ON にした直後の数十〜数百 ms 分だけが通り…`（twisty-purple）— ユーザーの曖昧な症状報告を既知の根本原因にマッピング。

## 6. 質問 vs 自律

**基本は自律実行型、判断が結果を大きく左右する分岐点では質問する。** ask_user_question は24回（うち17回は carnation-promotion の interview 指示による）。

- **質問する局面**: 破壊的操作の範囲（`~/.ollama` 4.8GB+秘密鍵を消すか / ultra-cotija）、仕様の意味が分岐する所（フィルターの patch 扱い / purple-restaurant）、事実でない前提（チームの Go 経験 / faithful-dragon）、CLI 設計の選択（three-conga）。
- **自律で進める局面**: 事実は自分で調べる（「事実なので調べます」と言って `npm view next version`）、検証・コミット・push・デプロイ・環境修復は許可範囲内で完遂。
- **指示のスコープ遵守**: 調査のみ・設計のみ・編集停止など、指示された停止線を厳密に守る（purple-restaurant / platinum-mustard / dedicated-basketball）。
- **対話の余地を残す報告**: 完了報告の末尾に「次の候補は CI 整備です」のような次アクション提案を添えるが、実行はユーザーの合意待ち。

**総評**: SWE-2 High は「測ってから言う」実測主義と「Wait,」に象徴される自己検証癖が強いエージェント。曖昧な日本語指示の解釈・外部ツールの quirk 切り分け・証拠を集めての原因特定に長ける。報告は構造化・正直・検証済み/未検証の区別付き。弱点はサブエージェント利用方針の不整合と、稀な一括操作の範囲外巻き込み。

**補足（親エージェントへ）**: `admitted-iberis.txt` はユーザープロンプトのみで AGENT 応答なし（3行）。`positive-curiosity`/`vine-wedge` は挨拶のみ。`get_output`/`exec` 等のツール名は digest の記述に基づく。