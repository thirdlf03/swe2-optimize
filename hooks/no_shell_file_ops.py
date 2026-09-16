#!/usr/bin/env python3
# @description: exec 内のファイル操作系コマンド(grep/find/cat/head/tail/cd)をブロックし専用ツールへ誘導する
# @hook-event: PreToolUse
# @hook-matcher: ^exec$
# @hook-timeout: 5
"""PreToolUse hook: block shell-side file ops that bypass dedicated tools.

Policy (command position only; quotes and heredocs respected):
  - `grep|egrep|fgrep|rg ...` as a command          -> BLOCK (use `grep` tool)
  - `find ...` as a command                          -> BLOCK (use `find_file_by_name`)
  - `cat <file>` standalone (no pipe, no redirect)   -> BLOCK (use `read` tool)
  - `head|tail <file>` standalone (not -f/-F/-c)     -> BLOCK (use `read` tool)
  - `cd <dir> && <cmd>` / `cd <dir>; <cmd>` as the
    first command of the whole string                -> BLOCK (use `workdir` param)

Allowed (not flagged):
  - `cmd | grep ...` — filtering stream output (documented exception)
  - `tail -f` / `tail -F` — streaming follow, `read` cannot do it
  - `cat` piping into another command — stream source, not a plain read
  - grep/find/cat inside heredoc bodies or quotes (e.g. `ssh host 'grep ...'`)
  - segments containing `$var`/backticks — tools can't take shell expansions
  - `cd` alone (persistent-shell navigation), `(cd dir && cmd)` subshells,
    `cd` inside loops, mid-command `cd` after the first segment
  - capability gaps the dedicated tools cannot express:
    `find` with predicates beyond name/type matching (`-newermt` and other
    time predicates, `-size`, `-perm`, `-empty`, `-exec`, `-delete`,
    `-prune`, `-printf`, `-regex`, `-type d|l|...` non-file types, ...)
    and grep-family flags for binary/multiline/PCRE/extract searches
    (`-a`/`--text`, `-U`/`--multiline`, `-P`/`--pcre2`, `-z`/`--null-data`,
    `-o`/`--only-matching`, `--byte-offset`)

On block, prints a JSON decision + reason on stdout and the reason on
stderr, then exits 2 (covers both JSON-decision and exit-code semantics).
"""
import json
import re
import sys

HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
ASSIGN_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:sudo\s+|command\s+|env\s+(?:\w+=\S+\s+)*)?"
)
DYNAMIC_RE = re.compile(r"[$`]")
GLOB_RE = re.compile(r"[*?[]")
GREP_RE = re.compile(r"^(?:e?grep|fgrep|rg)\b")
FIND_RE = re.compile(r"^find\b")

# find predicates the glob-based find_file_by_name tool cannot express
FIND_CAPS = {
    "-newer", "-anewer", "-cnewer", "-mtime", "-atime", "-ctime", "-Btime",
    "-mmin", "-amin", "-cmin", "-Bmin", "-perm", "-size", "-empty",
    "-delete", "-exec", "-execdir", "-ok", "-okdir", "-prune", "-printf",
    "-fprintf", "-ls", "-regex", "-iregex", "-xdev", "-mount", "-links",
    "-user", "-nouser", "-group", "-nogroup", "-inum", "-samefile",
    "-readable", "-writable", "-executable", "-used", "-quit", "-depth",
}
FIND_CAPS_PREFIX = ("-newer", "-anewer", "-cnewer")  # -newermt, -newerXt ...
# grep-family short-flag chars / long flags the dedicated grep tool lacks
GREP_CAP_CHARS = set("aUPzo")
GREP_CAP_LONG = {
    "--text", "--binary", "--multiline", "--pcre2", "--null-data",
    "--null", "--only-matching", "--byte-offset",
}


def tokens_outside_quotes(s: str):
    toks, cur, q = [], [], None
    for ch in s:
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch.isspace():
            if cur:
                toks.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        toks.append("".join(cur))
    return toks


def find_has_capability_gap(st2: str) -> bool:
    toks = tokens_outside_quotes(st2)
    for i, t in enumerate(toks):
        if t in FIND_CAPS or t.startswith(FIND_CAPS_PREFIX):
            return True
        if t == "-type" and i + 1 < len(toks) and toks[i + 1] != "f":
            return True
    return False


def grep_has_capability_gap(st2: str) -> bool:
    for t in tokens_outside_quotes(st2):
        if t in GREP_CAP_LONG:
            return True
        if t.startswith("-") and not t.startswith("--") and len(t) > 1:
            if any(c in GREP_CAP_CHARS for c in t[1:]):
                return True
    return False
CAT_RE = re.compile(r"^cat\b")
HT_RE = re.compile(r"^(head|tail)\b")
CD_RE = re.compile(r"^cd\s+(\S+)\s*$")
KW_RE = re.compile(r"^(?:do|then|else|elif)\s+")


def strip_heredocs(cmd: str) -> str:
    out, skip = [], None
    for ln in cmd.split("\n"):
        if skip is not None:
            if ln.strip() == skip:
                skip = None
            continue
        out.append(ln)
        m = HEREDOC_RE.search(ln)
        if m:
            skip = m.group(1)
    return "\n".join(out)


def split_segs(cmd: str):
    """Split on shell separators outside quotes.
    Returns [(is_command_position, text, separator_that_followed)]."""
    segs, cur = [], []
    i, n, q, pos = 0, len(cmd), None, True

    def emit(sep):
        nonlocal cur, pos
        segs.append((pos, "".join(cur), sep))
        cur = []

    while i < n:
        ch = cmd[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            elif ch == "\\" and i + 1 < n:
                cur.append(cmd[i + 1])
                i += 1
        else:
            if ch in "\"'":
                q = ch
                cur.append(ch)
            elif ch == "\\" and i + 1 < n:
                cur.append(ch)
                cur.append(cmd[i + 1])
                i += 1
            elif ch == "|":
                if cmd[i : i + 2] == "||":
                    emit("||")
                    pos = True
                    i += 1
                else:
                    emit("|")
                    pos = False
            elif ch == "&":
                if cmd[i : i + 2] == "&&":
                    emit("&&")
                    pos = True
                    i += 1
                else:
                    cur.append(ch)
            elif ch in ";\n":
                emit(ch)
                pos = True
            else:
                cur.append(ch)
        i += 1
    emit("")
    return segs


REASONS = {
    "grep": "`{cmd}` — file-content search via shell.\nUse the `grep` tool instead (pattern, path, glob_pattern, output_mode).",
    "find": "`{cmd}` — file search via shell.\nUse the `find_file_by_name` tool instead (pattern, path).",
    "cat": "`{cmd}` — file read via shell.\nUse the `read` tool instead (offset/limit paginate large files).",
    "ht": "`{cmd}` — file read via shell.\nUse the `read` tool instead (offset/limit paginate large files).",
    "cd": "`{cmd}` — directory change chained to the command.\nUse exec's `workdir` parameter instead (absolute path).",
}

FOOTER = """Still allowed: `cmd | grep` stream filters, `tail -f`, `cat f | cmd` stream sources,
`cd DIR` alone (persistent-shell navigation), subshell `(cd d && cmd)`,
and anything inside heredocs or ssh/remote quotes."""


def classify(cmd: str):
    """Return list of (kind, snippet) violations."""
    hits = []
    segs = split_segs(strip_heredocs(cmd))

    # `cd DIR &&/; <rest>` only when it is the FIRST command of the whole string
    for idx, (_pos, s, sep) in enumerate(segs):
        st = s.strip()
        if not st:
            continue
        st2 = ASSIGN_RE.sub("", st)
        m = CD_RE.match(st2)
        if (
            m
            and sep in ("&&", ";")
            and not DYNAMIC_RE.search(st2)
            and not m.group(1).startswith("~")
            and any(x[1].strip() for x in segs[idx + 1 :])
        ):
            hits.append(("cd", st2[:60]))
        break

    for pos, s, sep in segs:
        if not pos:
            continue
        st = s.strip()
        if not st:
            continue
        st2 = KW_RE.sub("", ASSIGN_RE.sub("", st))
        if DYNAMIC_RE.search(st2):
            continue
        if GREP_RE.match(st2):
            if not grep_has_capability_gap(st2):
                hits.append(("grep", st2[:60]))
        elif FIND_RE.match(st2):
            if not find_has_capability_gap(st2):
                hits.append(("find", st2[:60]))
        elif CAT_RE.match(st2):
            rest = st2[3:].strip()
            if (
                sep != "|"
                and "<<" not in st2
                and not GLOB_RE.search(rest)
                and not re.search(r"[<>]", rest)
                and rest
                and not rest.startswith("-")
                and not all(a in ("/dev/null", "-") for a in rest.split())
            ):
                hits.append(("cat", st2[:60]))
        elif HT_RE.match(st2):
            if sep == "|" or re.search(r"\s--?f(?:ollow)?\b", st2):
                continue
            rest = re.sub(r"^(?:head|tail)\s+", "", st2)
            rest = re.sub(
                r"^(?:-[a-zA-Z]*\d*\s+|-n\s*[+\d]\S*\s+|-c\s*\S+\s+)*", "", rest
            ).strip()
            if rest and not rest.startswith("-") and ">" not in rest and not GLOB_RE.search(rest):
                hits.append(("ht", st2[:60]))
    return hits


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return
    hits = classify(cmd)
    if not hits:
        return
    seen = []
    for kind, snip in hits:
        if kind not in [k for k, _ in seen]:
            seen.append((kind, snip))
    reason = "Blocked: shell-side file op(s) bypass the dedicated tools.\n" + "\n".join(
        REASONS[k].format(cmd=snip) for k, snip in seen
    ) + "\n\n" + FOOTER
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
    sys.stderr.write(reason + "\n")
    sys.exit(2)


main()
