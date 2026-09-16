---
name: writing-report
description: Devin CLI セッションログの調査手順と分析レポートの書き方。docs/ に新規レポートを作るときに使う
argument-hint: "[topic]"
allowed-tools:
  - read
  - grep
  - glob
  - find_file_by_name
  - exec
  - get_output
  - write
  - edit
  - todo_write
---

# 分析レポート作成手順

このrepoは Devin CLI (SWE-2) のセッションログから非効率・失敗パターンを見つけ、
「分析(docs/)」と「機械的対策(hooks/, bin/)」をセットで蓄積する。

## データソース

- `~/.local/share/devin/cli/transcripts/*.json` — ATIF形式トランスクリプト
  （steps, reasoning_content, tool_calls, observation を含む）
- `~/.local/share/devin/cli/sessions.db` — セッション/メッセージ/ツール呼出DB。
  **必ず `file:<path>?mode=ro&immutable=1` のURI指定で開く**（WALモードで開くと失敗することがある）
- 集計対象は `agent.model_name` が `SWE-2` 始まりのトランスクリプト

## 調査手順

1. **問いを1つに絞る** — 「何の無駄/失敗を、どの指標で観測するか」を先に決める
2. **定量集計** —
   ```bash
   python3 tools/aggregate.py   # 全transcripts走査 → digest生成
   python3 tools/aggregate2.py  # execコマンド分類・言語分布
   ```
   digest は `<OUT>/digests/<sid>.txt` に出る
   （USER発言 + AGENT発言 + THINK冒頭400字 + ツール名一覧 + TOOL_ERROR印）。
   全文が要る箇所は transcript 側を参照。
3. **digest精読** — 量が多ければ分割してサブエージェントに読ませる
   （前回は69セッションを3分割）。引用する事例はセッションslugと具体行を記録する
4. **再現確認** — 可能なら別環境・別DB・別期間で同パターンを確認する。
   1環境だけの観測は「環境固有の可能性」を残して断定しない
   （例: sleep乱打は別マシンのDBでも240-290秒クラスタが再現 → ドキュメント由来でなく
   モデルのデフォルト戦略と確定できた）
5. **根本原因を構造レベルで特定** — 「モデルが悪い」で止めない。
   プリミティブの欠落・ドキュメント未記載・ターン構造の制約など、
   「なぜその行動が合理的に見えたか」まで掘る

## レポートフォーマット (`docs/<topic>.md`)

- 主レポートは `docs/<topic>.md` に1ファイルで書く
- 詳細データ・分割レポート（tier別等）が増える場合は `docs/<topic>/` に置く
  （例: `docs/swe2-characteristics/medium.md`）

模範例: `docs/sleep-polling.md`（対策付き分析）、`docs/swe2-characteristics.md`（基礎データ型）

```markdown
> **出典**: セッション `<slug>`「<分析セッションのタイトル>」(YYYY-MM-DD)。
> データ: <何件の何を見たか>

# <トピック名>

## 観測データ
実測値つきの表。推測はここに書かない

## 根本原因
構造レベルの原因。設計上の問題は引用ブロックで指摘

## 悪いパターン / 良いパターン
| | 形 | 結果 |
|---|---|---|
| ❌ ... | | |
| ✅ ... | | |

## 対策
機械的に防げるなら hooks/ or bin/ に実装し、判定ルールとインストール手順を書く。
ブロック系は必ず「正しい代替手段」をセットで提示する

## 残課題・限界
対策を素通りできるケース・未検証の範囲を正直に書く
```

## 執筆ルール

- 観測(fact)と推測(hypothesis)を分ける。推測には根拠または「未確認」を付ける
- 数値は実測値で書く。「多い」ではなく「975回・15.4時間」
- 対策の優先順位: hooks/bin による強制 > ヘルパーの提供 > ルールへの記述。
  自然言語ルールは強制力を持たない（実測済み: AGENTS.md のルールは別マシンで無効だった）
- 試して棄却した対策も「なぜ棄却したか」と共に記録する（再検討の無駄を防ぐ）
- **個人情報・非公開プロジェクト名・ユーザー発言の生引用を書かない**
  （スキャンは `/check-report`）

## 既存レポートとの重複

調査結果が既存 `docs/` と重なる場合、新規ファイルを立てる前にまず既存を確認する:

| 状況 | 対応 |
|---|---|
| 同一トピックの追加観測・続報 | 既存 `docs/<topic>.md` に「追記(YYYY-MM-DD)」セクションで追記（例: env-hardening.md の効果検証） |
| 既存の結論を覆す・修正する | 既存 doc の該当箇所を更新し、何が変わったか日付つきで残す（実施結果表の状態更新のように） |
| 別トピックだが関連する | 新規 `docs/<topic>.md` を作り、関連レポートへ相互リンクする |

README のトピック表は「問題」の単位で管理する。同一問題への追記は表の行を増やさず、
既存行の分析リンクが最新docを指していればよい。

## 完了前に

1. `README.md` のトピック表に1行追加
2. `/check-report` でプライバシースキャンする
3. main に直接コミットせず、ブランチを切って PR を作る（公開repoのため）
