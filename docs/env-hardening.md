> **出典**: セッション `enchanting-bead`「Devin CLI SWE-2 全セッション分析と特徴抽出」(2026-09-15)。
> `~/.local/share/devin/cli/sessions.db` のメッセージから復元。元の作業ディレクトリは空のため、本ファイルが唯一の永続コピー。

---

# SWE-2 の性能を活かす環境整備プラン

## 現状の診断結果(実測)

69セッションの分析で見えた、コンテキスト・挙動上の具体的な問題:

| 問題 | 実測値 |
|---|---|
| スキルの重複登録 | 16件中6件が完全な同一ファイルの重複(orca-cli×3、orchestration×3、find-docs×2、find-skills×2、grilling×2)。`available_skills` ブロックは4.7→6.4KBに膨張中 |
| スキル使用率 | 69セッションで呼ばれたのは devin-cli×5, grilling×3, orchestration×3, agy-writing×1 のみ。**find-docs / find-skills / orca-cli / docs-research / vercel-react-best-practices / web-design-guidelines は0回** |
| ルール競合 | `~/.claude/CLAUDE.md` のオーケストレーション規約は Claude Code 用(researcher/implementer/Opus 5 等は Devin に存在しない)。Devin の「明示要求までsubagent禁止」と衝突し、**ほぼ毎セッション THINK で再検討+結論が揺れる**無駄が発生 |
| ルール多重注入 | マルチworktree作業で同じ AGENTS.md がアクセスしたディレクトリ毎に再注入。chip-chinchilla で**41KB**(4回重複)、good-equipment 28KB |
| 巨大ルールファイル | あるrepoの `CLAUDE.md` が **29.5KB**(AGENTS.md から `@CLAUDE.md` で import)→ そのrepoのセッションで18KB注入 |
| 権限プロンプト | `.devin/config.json` の allow 設定があるのは1repoのみ。Normalモードでは exec/fetch/write が毎回プロンプト → SWE-2 の長いツールチェーンが途中停止する |

## 提案(効果順)

### 1. `read_config_from` で Claude/Cursor 由来の import を遮断 ←最重要

`~/.config/devin/config.json` に追加:

```json
"read_config_from": {
  "claude": false,
  "cursor": false
}
```

これ一発で: `.claude/skills`・`.cursor/skills` の取り込みが止まり、**競合元の `~/.claude/CLAUDE.md` も注入されなくなる**。Claude Code / Cursor 本体側のファイルは残るので、他ツール運用は壊れません(`agents_standard` は true のまま → AGENTS.md は有効維持)。

### 2. スキルを一箇所に正本化

import 遮断後も `.agents/skills` と `.config/devin/skills` で orca-cli/orchestration が重複します。方針:

- **正本は `~/.agents/skills/`**(クロスツール標準)に集約 → `.config/devin/skills/` 側の重複分を削除
- 使用実績0の `find-docs`, `find-skills`, `docs-research` は削除(web_search+context7 MCPで代替済み)
- `vercel-react-best-practices` / `web-design-guidelines` は使うなら当該repoの `.devin/skills/` に移してプロジェクトスコープ化
- `~/.claude/skills/learned/` は空ディレクトリ → 削除

### 3. グローバルルールを Devin 向けに書き直し

`~/.claude/CLAUDE.md` の中で Devin にも残したい内容(委任方針・報告の正直さ等)を **`~/.config/devin/AGENTS.md`** に移植。書き直しの要点:

- 存在しない agent 名を `subagent_explore`(安い SWE-1.6、調査用)/ `subagent_general`(親と同じモデル=Maxでは高コスト、実装用)に修正
- 「この規約は subagent 使用の明示的な許可とみなす」と一行書く → 毎セッションのルール解釈迷いが消える
- 公式推奨に従い**ルールは最小限に**。委任プロンプトの書き方のような詳細手順は always-on ではなくスキル(orchestration スキル側)に寄せる

### 4. あるrepoの巨大 CLAUDE.md を分割

29.5KB は always-on にしては大きすぎます(公式も「rulesは最小限に」を明記)。コマンド一覧・アーキテクチャ要点だけ AGENTS.md に残し、環境変数の全リスト等は `docs/` かスキルに逃がすのが効果的です。

### 5. 権限設定でストールを減らす ←自律性に直結

SWE-2 は長いツールチェーンを回すので、プロンプト停止は性能を直接殺します。

- 手軽な方: **`/mode smart` または `devin --permission-mode smart`** — 安全と判定された操作は自動承認(パッケージinstall・破壊的git・rm/sudo は常にプロンプトのまま)
- 確実な方: あるrepoの `.devin/config.json` の allow リストを各アクティブrepoに展開。雛形はそのまま使えます

### 6. 判断が要る項目

- **Orca フック**: 8イベント全て(毎ツール呼び出し含む)で `devin-hook.sh` が起動。Orca を常用するなら維持が無難(Orca が管理している設定で、消すと連携が途切れ、再生成される可能性もあり)
- **サブエージェント自体**: 委任スタイルを捨ててSWE-2に全部やらせるなら `subagents_enabled: false` もアリ(ツール自体が消えて迷いがゼロになる)
- **AGENTS.md の大きさ**: マルチworktree運用ではアクセス毎に再注入されるので、あるrepoの契約書ブロック(型定義)のような大きな塊は別ファイル参照化が有効

### 優先度まとめ

1 + 2 + 3 はセット(コンテキスト毎セッション数KB削減+競合解消)、4 は特定repoで効く、**5 が体感上いちばん効く**(自律性)。

必要ならこの内容で実際に config 編集・ファイル整理までやります。どこまでやりましょうか?
---

## 実施結果（2026-09-15 実施済み）

上記プランのうち実際に適用されたもの:

| 項目 | 状態 |
|---|---|
| 1. `read_config_from` 遮断 | ✅ 実施済み — `~/.config/devin/config.json` に `"claude": false, "cursor": false` |
| 2. スキル正本化 | ✅ 実施済み — 正本は `~/.agents/skills/`。重複(orca-cli, orchestration)・未使用(find-docs, find-skills, docs-research, vercel-react-best-practices, web-design-guidelines, agy-writing)を削除。`.claude/skills/learned/`(空)も削除 |
| 3. グローバルルール | ✅ 実施済み — `~/.config/devin/AGENTS.md` 新設(4条)。旧オーケストレーション規約は移植せず |
| 4. 巨大 CLAUDE.md 分割 | ❌ 未実施 |
| 5. permission-mode | 要確認 — config.json に permission_mode 設定は見当たらない(未実施の可能性) |
| 6. サブエージェント | ❌ 廃止(2026-09-16) — 4プロファイルを作成・`~/.config/devin/agents/` に配置したが、built-in との役割重複・全セッションへの description 注入コストを考慮し削除 |

### 対策の効果検証（2026-09-16 追記）

sleep ポーリング対策は AGENTS.md の自然言語ルール(1条目)として導入されたが、
**別マシンの sessions.db では同問題が 975回・15.4時間分観測された**。
自然言語ルールは機械的強制力を持たないため、PreToolUse フックによる強制に格上げした。
→ [docs/sleep-polling.md](sleep-polling.md) / [hooks/no_blind_sleep.py](../hooks/no_blind_sleep.py)

教訓: **AGENTS.md のルールは「分析結果の備忘」としては有効だが、頻出する失敗パターンには hooks での強制が必要。**

### 注入量の実測検証（2026-09-16 追記 — context-cost 分析から）

全85セッションの step metrics を使って冒頭注入量を実測した結果:

- 対策後(9/15夕〜)の冒頭注入は **19.4KB 固定**に収束（対策前は中央値~21KB・最大112.5KB）
- `.claude/CLAUDE.md`・`.cursor` 由来の注入は **0件**（`read_config_from` 遮断が実際に効いている）
- `available_skills` ブロックは 4,731〜6,415B → **2,829B** に縮小（スキル正本化の効果）
- 残る大きな冒頭注入は resume summary（26〜40KB）のみ — これは汚染ではなくコンパクション要約

詳細・tokenコスト全体の分析は [docs/context-cost.md](context-cost.md)。
