#!/usr/bin/env python3
# @description: リモート書き込み系コマンド(git push / gh 書き込み / publish / deploy)をブロックし、ユーザー承認→bin/remote-write-approved 経由を強制する
# @hook-event: PreToolUse
# @hook-matcher: ^(exec|write_to_process)$
# @hook-timeout: 5
"""PreToolUse hook: gate remote-write shell commands behind explicit approval.

Blocks command-position occurrences of remote-mutating commands:
  - git push
  - gh pr|issue|release|repo|gist|label|project|run|workflow|secret|variable|cache
    write subcommands
  - gh api mutations (-X/--method POST|PUT|PATCH|DELETE, -f/-F on non-graphql
    endpoints, graphql `mutation` queries)
  - package publishes (npm/pnpm/yarn/bun publish, cargo publish, gem push,
    twine upload, poetry publish)
  - deploys (docker push, kubectl apply|create|delete|patch|replace|scale,
    helm install|upgrade|uninstall|rollback, terraform apply|destroy,
    wrangler deploy|publish, vercel deploy|--prod, netlify deploy, fly deploy)

A blocked call explains the approval flow: ask the user first, then run
`remote-write-approved [scope]` which writes a short-lived token to
~/.local/state/devin/remote-write-approval.json. While a token covering the
detected scope is fresh (< TOKEN_TTL_S), the same commands pass.

This hook is a CHECKPOINT, not a security boundary: an agent could run the
approve script without asking. The point is to make "write to remote without
asking" impossible to do *accidentally*, and to leave an audit trail in
~/.local/state/devin/remote-write-approvals.log.
"""
import json
import os
import re
import sys
import time

STATE_DIR = os.path.expanduser("~/.local/state/devin")
TOKEN_PATH = os.path.join(STATE_DIR, "remote-write-approval.json")
TOKEN_TTL_S = 600

HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
ASSIGN_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:sudo\s+|command\s+|env\s+(?:\w+=\S+\s+)*)?"
)
KW_RE = re.compile(r"^(?:do|then|else|elif)\s+")

# scope -> list of (pattern on the stripped command-position segment)
WRITE_RULES = [
    ("git-push", [re.compile(r"^git\s+push\b")]),
    (
        "gh-pr",
        [re.compile(r"^gh\s+pr\s+(?:create|merge|close|reopen|edit|review|comment|ready|lock|unlock|update-branch|checkout\s+--)")],
    ),
    (
        "gh-issue",
        [re.compile(r"^gh\s+issue\s+(?:create|edit|close|reopen|comment|delete|pin|unpin|transfer|lock|unlock|develop)\b")],
    ),
    ("gh-release", [re.compile(r"^gh\s+release\s+(?:create|edit|delete|upload|edit-asset|delete-asset)\b")]),
    (
        "gh-repo",
        [re.compile(r"^gh\s+repo\s+(?:create|edit|delete|rename|archive|unarchive|deploy-key|secret|variable|set-default|set-visibility)\b")],
    ),
    ("gh-gist", [re.compile(r"^gh\s+gist\s+(?:create|edit|delete)\b")]),
    ("gh-label", [re.compile(r"^gh\s+label\s+(?:create|edit|delete|clone)\b")]),
    ("gh-project", [re.compile(r"^gh\s+project\s+(?:create|edit|delete|close|mark-template|item-add|item-delete|item-edit|item-archive)\b")]),
    (
        "gh-run",
        [re.compile(r"^gh\s+run\s+(?:rerun|cancel|delete|download\s+--)\b"), re.compile(r"^gh\s+workflow\s+(?:run|enable|disable)\b")],
    ),
    ("gh-config", [re.compile(r"^gh\s+(?:secret|variable)\s+(?:set|delete)\b"), re.compile(r"^gh\s+cache\s+delete\b")]),
    ("publish", [
        re.compile(r"^(?:npm|pnpm|yarn|bun)\s+publish\b"),
        re.compile(r"^npm?\s+.*\bpublish\b"),
        re.compile(r"^cargo\s+publish\b"),
        re.compile(r"^gem\s+push\b"),
        re.compile(r"^twine\s+upload\b"),
        re.compile(r"^poetry\s+publish\b"),
    ]),
    ("deploy", [
        re.compile(r"^docker\s+push\b"),
        re.compile(r"^kubectl\s+(?:apply|create|delete|patch|replace|scale|rollout\s+undo|drain|cordon|taint|label|annotate)\b"),
        re.compile(r"^helm\s+(?:install|upgrade|uninstall|rollback|push)\b"),
        re.compile(r"^terraform\s+(?:apply|destroy|import|taint|untaint|state\s+rm|state\s+mv)\b"),
        re.compile(r"^wrangler\s+(?:deploy|publish|delete|kv:key\s+put|r2\s+object\s+put)\b"),
        re.compile(r"^vercel\b[^|;&]*(?:--prod|deploy|promote|rollback|rm|remove|env\s+add|secrets\s+add)"),
        re.compile(r"^netlify\s+deploy\b[^|;&]*--prod"),
        re.compile(r"^fly(?:ctl)?\s+(?:deploy|scale|secrets\s+set|volumes\s+destroy|apps\s+destroy)\b"),
    ]),
]

GH_API_RE = re.compile(r"^gh\s+api\b")
GH_API_METHOD_RE = re.compile(r"(?:-X|--method)[=\s]+(POST|PUT|PATCH|DELETE)\b")
GH_API_FIELD_RE = re.compile(r"(?:^|\s)-[fF][=\s]")
GH_API_GRAPHQL_RE = re.compile(r"^gh\s+api\s+graphql\b")
GH_API_MUTATION_RE = re.compile(r"\bmutation\b")


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
    Returns [(is_command_position, text)] — content after a pipe is not
    command position for our purposes."""
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


def gh_api_scope(seg: str):
    """Return scope if this `gh api` call mutates remote state, else None."""
    if GH_API_METHOD_RE.search(seg):
        return "gh-api"
    if GH_API_GRAPHQL_RE.match(seg):
        return "gh-api" if GH_API_MUTATION_RE.search(seg) else None
    # `gh api <path>` with form fields is a POST (non-graphql endpoints only)
    if GH_API_FIELD_RE.search(seg):
        return "gh-api"
    return None


def classify(cmd: str):
    """Return list of (scope, snippet) violations."""
    hits = []
    segs = split_segs(strip_heredocs(cmd))
    for pos, s, sep in segs:
        if not pos:
            continue
        st = KW_RE.sub("", ASSIGN_RE.sub("", s.strip()))
        if not st:
            continue
        if GH_API_RE.match(st):
            sc = gh_api_scope(st)
            if sc:
                hits.append((sc, st[:70]))
            continue
        for scope, rules in WRITE_RULES:
            if any(r.match(st) for r in rules):
                hits.append((scope, st[:70]))
                break
    return hits


def approved_scopes():
    """Return (set_of_scopes, age_s) if a fresh token exists, else (set(), None)."""
    try:
        with open(TOKEN_PATH) as f:
            tok = json.load(f)
        age = time.time() - float(tok.get("ts", 0))
        if age > TOKEN_TTL_S:
            return set(), age
        scopes = set(tok.get("scopes") or [])
        return scopes, age
    except Exception:
        return set(), None


REASON = """Blocked: remote-write command `{cmd}` needs explicit user approval first.

Flow: (1) ask the user for approval and wait for a yes,
      (2) run `remote-write-approved {scope}` (or `all`),
      (3) retry the command — the gate opens for {ttl}s.

Do NOT run remote-write-approved before the user approves: the script is a
checkpoint so the *user* controls when remote state changes. Bypassing it
without approval defeats the purpose (bypasses are logged)."""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    ti = data.get("tool_input") or {}
    cmd = ti.get("command") or ti.get("text_input") or ti.get("bytes_input") or ""
    if not cmd:
        return
    hits = classify(cmd)
    if not hits:
        return

    scopes, _age = approved_scopes()
    if "all" in scopes or all(s in scopes for s, _ in hits):
        return

    need = sorted({s for s, _ in hits})
    scope_arg = " ".join(need) if len(need) <= 2 else "all"
    reason = REASON.format(cmd=hits[0][1], scope=scope_arg, ttl=TOKEN_TTL_S)
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
    sys.stderr.write(reason + "\n")
    sys.exit(2)


main()
