# tools/ — セッション分析スクリプト

前回分析(2026-09-15, セッション `enchanting-bead`)で使われた集計スクリプト。
`/tmp/swe2_analysis/` に置かれていたものを救出（/tmp は再起動で消える）。

## データソース

- `~/.local/share/devin/cli/transcripts/*.json` — ATIF 形式のトランスクリプト
  （steps, reasoning_content, tool_calls, observation を含む）
- `~/.local/share/devin/cli/sessions.db` — セッション/メッセージ/ツール呼出のDB

## aggregate.py

全トランスクリプトを走査し、モデル別に以下を集計:

- セッション一覧（ステップ数・user/agent メッセージ数・期間）
- 推論量・発言量（文字/step）
- ツール頻度・並列呼出率・ツールエラー数
- 各セッションの digest ファイルを `<OUT>/digests/<sid>.txt` に生成
  （USER発言 + AGENT発言 + THINK冒頭400字 + ツール名一覧 + TOOL_ERROR印）

`OUT` を変更すれば出力先を変えられる。digest は「全文精読」型分析の前処理として使う
（69セッション分を3分割してサブエージェントに読ませる、等）。

## cache_miss.py

step 単位の `prompt_tokens`/`cached_tokens` から「フルprefixキャッシュミス」
（cached < 直前promptの90%）を検出し、イベント数・トリガー分布・
ワーストセッションを出力する。分析は docs/context-cost.md。

## aggregate2.py

exec コマンドの分類集計（git / gh / test・lint・build / 探索系）、
セッション時間、発言・推論の言語分布（日/英）。

## 使い方

```bash
python3 tools/aggregate.py    # digests を /tmp/swe2_analysis/digests に生成
python3 tools/aggregate2.py   # コマンド分類・言語分布をstdoutに出力
```

## 注意

- transcripts の `agent.model_name` が `SWE-2` 始まりのものだけ対象
- digest の THINK は先頭400字に切り詰め（全文は transcript 側を参照）
- sessions.db は WAL モードで開くと失敗することがある。
  `file:...?mode=ro&immutable=1` の URI 指定で開くこと
