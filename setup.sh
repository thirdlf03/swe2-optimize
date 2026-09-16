#!/bin/sh
# setup.sh — swe2-optimize の対策(hooks/bin/推奨設定)を対話的に適用・解除する
#
#   ./setup.sh          対話モード (各項目を y/n で選択)
#   ./setup.sh -y       全て Yes (symlink インストール)
#   ./setup.sh --copy   コピーでインストール
#   ./setup.sh -u       アンインストール
#   ./setup.sh -h       ヘルプ
#
# hooks/* はファイル先頭のメタデータ行から登録情報を読む:
#   # @description: 説明文          (任意)
#   # @hook-event: PreToolUse       (必須。無いファイルは無視)
#   # @hook-matcher: ^(exec|...)$   (任意。省略時は全ツール)
#   # @hook-timeout: 5              (任意。デフォルト5秒)
# bin/* は `# @description:` のみ使い、~/.local/bin/ に置く。

set -u

# ============ 定数 ============

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
DEVIN_DIR="$HOME/.config/devin"
CONFIG="$DEVIN_DIR/config.json"
HOOK_DEST_DIR="$DEVIN_DIR/hooks"
BIN_DEST_DIR="$HOME/.local/bin"
RCF_FRAGMENT='{"read_config_from": {"claude": false, "cursor": false}}'

YES=0; UNINSTALL=0; METHOD=''
BACKED_UP=0; CONFIG_OK=1; CHANGED=0

# ============ 表示 ============

if [ -t 1 ]; then
  _e=$(printf '\033')
  B="${_e}[1m"; G="${_e}[32m"; Y="${_e}[33m"; C="${_e}[36m"
  R="${_e}[31m"; D="${_e}[2m"; X="${_e}[0m"
else
  B=''; G=''; Y=''; C=''; R=''; D=''; X=''
fi

section() { printf '\n%s== %s ==%s\n' "$B$C" "$1" "$X"; }
item()    { printf '\n%s● %s%s\n' "$B" "$1" "$X"; }
say()     { printf '   %s\n' "$*"; }
dim()     { printf '   %s%s%s\n' "$D" "$*" "$X"; }
ok()      { printf '   %s✓%s %s\n' "$G" "$X" "$*"; }
warn()    { printf '   %s!%s %s\n' "$Y" "$X" "$*"; }
err()     { printf '%s✗ %s%s\n' "$R" "$*" "$X" >&2; }
die()     { err "$*"; exit 1; }

# ask <質問> [Y|n] — yes なら 0 を返す
ask() {
  _def=${2:-Y}
  [ "$_def" = Y ] && _p='Y/n' || _p='y/N'
  if [ "$YES" = 1 ]; then
    printf '   %s?%s %s [%s] -> yes\n' "$C" "$X" "$1" "$_p"
    return 0
  fi
  printf '   %s?%s %s [%s] ' "$C" "$X" "$1" "$_p"
  read -r _a || _a=''
  case "$_a" in
    y|Y|yes|Yes) return 0 ;;
    n|N|no|No)   return 1 ;;
    *)           [ "$_def" = Y ] ;;
  esac
}

choose_method() {
  [ -n "$METHOD" ] && return 0
  if [ "$YES" = 1 ]; then METHOD='link'; return 0; fi
  say "インストール方法:"
  say "  1) symlink  repoのファイルを参照。repo更新が即反映 ${B}(推奨)${X}"
  say "  2) copy     複製を置く。repoを動かしても壊れない"
  printf '   %s?%s [1] ' "$C" "$X"
  read -r _a || _a=''
  case "$_a" in
    2|copy) METHOD='copy' ;;
    *)      METHOD='link' ;;
  esac
}

# meta <file> <key> — 先頭コメントの `# @key: value` を返す
meta() { sed -n "s/^# @$2: //p" "$1" | head -n 1; }

# ============ ファイルの配置/撤去 ============

install_file() { # <src> <dst>
  _src=$1; _dst=$2
  mkdir -p "$(dirname "$_dst")" || die "mkdir failed: $_dst"
  chmod +x "$_src"
  if [ "$METHOD" = link ]; then
    if [ -L "$_dst" ] && [ "$(readlink "$_dst")" = "$_src" ]; then
      dim "link済み: $_dst"; return 0
    fi
    ln -sfn "$_src" "$_dst" || die "ln failed: $_dst"
  else
    if [ -f "$_dst" ] && cmp -s "$_src" "$_dst"; then
      dim "最新です: $_dst"; return 0
    fi
    cp "$_src" "$_dst" || die "cp failed: $_dst"
    chmod +x "$_dst"
  fi
  ok "$METHOD -> $_dst"
  CHANGED=1
}

# installed_file <src> <dst> — dst が src を指すlink or 同一内容の実ファイルなら 0
installed_file() {
  _src=$1; _dst=$2
  if [ -L "$_dst" ]; then
    [ "$(readlink "$_dst")" = "$_src" ]
  elif [ -f "$_dst" ]; then
    cmp -s "$_src" "$_dst"
  else
    return 1
  fi
}

remove_file() { # <src> <dst> — repoを指すlink or 同一内容のコピーだけ消す
  _src=$1; _dst=$2
  if [ -L "$_dst" ]; then
    if [ "$(readlink "$_dst")" = "$_src" ]; then
      rm "$_dst" && { ok "removed: $_dst"; CHANGED=1; }
    else
      warn "別のリンク先なので残します: $_dst -> $(readlink "$_dst")"
    fi
  elif [ -f "$_dst" ]; then
    if cmp -s "$_src" "$_dst"; then
      rm "$_dst" && { ok "removed: $_dst"; CHANGED=1; }
    elif ask "$_dst はrepoと内容が異なる実ファイルです。削除する" n; then
      rm "$_dst" && { ok "removed: $_dst"; CHANGED=1; }
    else
      dim "残します: $_dst"
    fi
  else
    dim "not installed: $_dst"
  fi
}

backup_config() {
  [ "$BACKED_UP" = 1 ] && return 0
  [ -f "$CONFIG" ] || return 0
  _b="$CONFIG.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$CONFIG" "$_b" && dim "backup: $_b"
  BACKED_UP=1
}

# ============ config.json 操作 (全てここに集約) ============
#
# cfg <op> [args...]
#   check                                config が JSON として読めるか
#   has-hook <cmd>...                    どれかの command が登録済みなら 0
#   add-hook <event> <matcher> <cmd> <timeout>
#   del-hook <cmd>...                    command 一致を全イベントから除去
#   has-rcf / has-rcf-any                read_config_from 遮断が 両方/どれか 設定済みなら 0
#   del-rcf                              自分が入れた claude/cursor:false を除去
#   merge <json-fragment>                dict を深くマージ
#
cfg() {
  python3 - "$CONFIG" "$@" <<'PYEOF'
import json, os, sys, tempfile

path, op, args = sys.argv[1], sys.argv[2], sys.argv[3:]

def load():
    return json.load(open(path)) if os.path.exists(path) else {}

def save(cfg):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                               prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)

def hooks_iter(cfg):
    for event, groups in (cfg.get("hooks") or {}).items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                yield h

def rcf():
    return load().get("read_config_from") or {}

if op == "check":
    try:
        load()
    except Exception:
        sys.exit(1)

elif op == "has-hook":
    try:
        cfg = load()
    except Exception:
        sys.exit(1)
    cmds = set(args)
    sys.exit(0 if any(h.get("command") in cmds for h in hooks_iter(cfg)) else 1)

elif op == "add-hook":
    event, matcher, command, timeout = args
    cfg = load()
    entry = {}
    if matcher:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": command,
                       "timeout": int(timeout)}]
    cfg.setdefault("hooks", {}).setdefault(event, []).append(entry)
    save(cfg)

elif op == "del-hook":
    cmds = set(args)
    cfg = load()
    hooks = cfg.get("hooks") or {}
    changed = False
    for event, groups in list(hooks.items()):
        kept = []
        for g in groups or []:
            hs = g.get("hooks") or []
            new_hs = [h for h in hs if h.get("command") not in cmds]
            if len(new_hs) != len(hs):
                changed = True
            if new_hs:
                g["hooks"] = new_hs
                kept.append(g)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
            if groups:
                changed = True
    if not changed:
        sys.exit(1)
    save(cfg)

elif op == "has-rcf":
    r = rcf()
    sys.exit(0 if r.get("claude") is False and r.get("cursor") is False else 1)

elif op == "has-rcf-any":
    r = rcf()
    sys.exit(0 if any(r.get(k) is False for k in ("claude", "cursor")) else 1)

elif op == "del-rcf":
    try:
        cfg = load()
    except Exception:
        sys.exit(1)
    r = cfg.get("read_config_from")
    if not isinstance(r, dict):
        sys.exit(1)
    hit = [k for k in ("claude", "cursor") if r.get(k) is False]
    if not hit:
        sys.exit(1)
    for k in hit:
        del r[k]
    if not r:
        del cfg["read_config_from"]
    save(cfg)

elif op == "merge":
    cfg = load()
    frag = json.loads(args[0])
    def merge(d, s):
        for k, v in s.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                merge(d[k], v)
            else:
                d[k] = v
    merge(cfg, frag)
    save(cfg)

else:
    sys.exit("unknown cfg op: " + op)
PYEOF
}

# ============ 各項目の処理 ============

setup_hook() { # <file>
  _f=$1; _name=$(basename "$_f")
  _event=$(meta "$_f" hook-event)
  item "$_name"
  if [ -z "$_event" ]; then
    warn "@hook-event 行が無いのでskip"
    return
  fi
  _desc=$(meta "$_f" description)
  [ -n "$_desc" ] && say "$_desc"
  _matcher=$(meta "$_f" hook-matcher)
  _timeout=$(meta "$_f" hook-timeout); _timeout=${_timeout:-5}
  _dest="$HOOK_DEST_DIR/$_name"
  dim "event: $_event / matcher: ${_matcher:-(all)} / timeout: ${_timeout}s"

  if installed_file "$_f" "$_dest" && \
     { [ "$CONFIG_OK" != 1 ] || cfg has-hook "$_dest" "$_f"; }; then
    dim "セットアップ済み"
    return
  fi
  ask "このhookを有効化する" Y || { dim "skip"; return; }
  choose_method
  install_file "$_f" "$_dest"

  [ "$CONFIG_OK" = 1 ] || return 0
  if cfg has-hook "$_dest" "$_f"; then
    dim "config.json: 登録済み"
    return
  fi
  if [ -n "$_matcher" ]; then
    _entry="{\"matcher\": \"$_matcher\", \"hooks\": [{\"type\": \"command\", \"command\": \"$_dest\", \"timeout\": $_timeout}]}"
  else
    _entry="{\"hooks\": [{\"type\": \"command\", \"command\": \"$_dest\", \"timeout\": $_timeout}]}"
  fi
  dim "config.json hooks.$_event に追加:"
  say "$_entry"
  ask "追加する" Y || { dim "skip"; return; }
  backup_config
  if cfg add-hook "$_event" "$_matcher" "$_dest" "$_timeout"; then
    ok "config.json: 登録しました"; CHANGED=1
  else
    err "config.json への登録に失敗"
  fi
}

setup_bin() { # <file>
  _f=$1; _name=$(basename "$_f")
  item "$_name"
  _desc=$(meta "$_f" description)
  [ -n "$_desc" ] && say "$_desc"
  if installed_file "$_f" "$BIN_DEST_DIR/$_name"; then
    dim "セットアップ済み"
    return
  fi
  ask "$BIN_DEST_DIR にインストールする" Y || { dim "skip"; return; }
  choose_method
  install_file "$_f" "$BIN_DEST_DIR/$_name"
}

setup_rcf() {
  section "推奨設定 -> $CONFIG"
  if [ "$CONFIG_OK" != 1 ]; then
    warn "config.json が読めないためskip"
  elif cfg has-rcf; then
    dim "read_config_from 遮断: 設定済み"
  else
    item "read_config_from 遮断"
    say "Claude/Cursor の設定取り込みを遮断し、スキル重複・ルール競合を防ぐ"
    dim "根拠: docs/env-hardening.md 提案1"
    say "追加: $RCF_FRAGMENT"
    if ask "追加する" Y; then
      backup_config
      if cfg merge "$RCF_FRAGMENT"; then
        ok "追加しました"; CHANGED=1
      else
        err "追加に失敗"
      fi
    else
      dim "skip"
    fi
  fi
}

uninstall_all() {
  section "uninstall"
  for _f in "$REPO"/hooks/*; do
    [ -f "$_f" ] || continue
    [ -n "$(meta "$_f" hook-event)" ] || continue
    _name=$(basename "$_f"); _dest="$HOOK_DEST_DIR/$_name"
    item "$_name"
    remove_file "$_f" "$_dest"
    if [ "$CONFIG_OK" = 1 ] && cfg has-hook "$_dest" "$_f"; then
      backup_config
      if cfg del-hook "$_dest" "$_f"; then
        ok "config.json: 登録を削除"; CHANGED=1
      else
        err "config.json: 削除失敗"
      fi
    else
      dim "config.json: 未登録"
    fi
  done
  for _f in "$REPO"/bin/*; do
    [ -f "$_f" ] || continue
    _name=$(basename "$_f")
    item "$_name"
    remove_file "$_f" "$BIN_DEST_DIR/$_name"
  done
  if [ "$CONFIG_OK" = 1 ]; then
    echo
    if ask "read_config_from 遮断 (claude/cursor:false) も解除する" Y; then
      if cfg has-rcf-any; then
        backup_config
        if cfg del-rcf; then
          ok "解除しました"; CHANGED=1
        else
          err "解除に失敗"
        fi
      else
        dim "対象の設定はありません"
      fi
    else
      dim "read_config_from はそのまま残します"
    fi
  fi
}

# ============ main ============

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)       YES=1 ;;
    -u|--uninstall) UNINSTALL=1 ;;
    --link)         METHOD='link' ;;
    --copy)         METHOD='copy' ;;
    -h|--help)      usage; exit 0 ;;
    *)              die "unknown option: $1 (-h でヘルプ)" ;;
  esac
  shift
done

printf '%sswe2-optimize setup%s\n' "$B" "$X"
printf '%srepo:   %s%s\n' "$D" "$REPO" "$X"
printf '%sconfig: %s%s\n' "$D" "$CONFIG" "$X"

command -v python3 >/dev/null 2>&1 || die "python3 が必要です (hook実行とconfig編集に使用)"
mkdir -p "$DEVIN_DIR" "$HOOK_DEST_DIR" "$BIN_DEST_DIR" || die "ディレクトリ作成に失敗"
if [ -f "$CONFIG" ] && ! cfg check; then
  CONFIG_OK=0
  warn "$CONFIG が JSON として読めません。config の読み書きはスキップします"
fi

if [ "$UNINSTALL" = 1 ]; then
  uninstall_all
else
  section "hooks -> $HOOK_DEST_DIR"
  for _f in "$REPO"/hooks/*; do
    [ -f "$_f" ] || continue
    setup_hook "$_f"
  done
  section "bin -> $BIN_DEST_DIR"
  for _f in "$REPO"/bin/*; do
    [ -f "$_f" ] || continue
    setup_bin "$_f"
  done
  setup_rcf
  case ":$PATH:" in
    *":$BIN_DEST_DIR:"*) ;;
    *) warn "$BIN_DEST_DIR が PATH に含まれていません" ;;
  esac
fi

section "完了"
if [ "$CHANGED" = 1 ]; then
  ok "変更あり。新しい devin セッションから反映されます"
else
  dim "変更はありませんでした"
fi
