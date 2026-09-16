#!/usr/bin/env python3
# @description: 無条件の sleep 待機をブロックし、条件待ち(until/while + wait-for等)へ誘導する
# @hook-event: PreToolUse
# @hook-matcher: ^(exec|write_to_process)$
# @hook-timeout: 5
"""PreToolUse hook: block blind/unconditional `sleep` waits.

Policy:
  - `sleep N` (N >= 15) outside a condition loop          -> BLOCK
  - pure time-wasting (`sleep N` alone / with no-ops, N>=5) -> BLOCK
  - sleep inside `until|while|for ... done` loop           -> ALLOW
    (the sleep is the poll interval of a condition wait)
  - short sleeps (< 15) alongside a real command           -> ALLOW

On block, prints a JSON decision + reason on stdout and the reason on
stderr, then exits 2 (covers both JSON-decision and exit-code semantics).
"""
import json
import re
import sys

MIN_BLOCK_S = 15.0
WASTE_MIN_S = 5.0

# loop keywords only count in command position (start or after ; & | ( { ' " do)
LOOP_OPEN = re.compile(r"(?:^|[;&|({\"'\n]|&&|\|\||\bdo\b)\s*(?:until|while|for)\b")
LOOP_CLOSE = re.compile(r"(?:^|[;&|)}\"'\n]|&&|\|\|)\s*done\b")
SLEEP_RE = re.compile(r"\bsleep\s+([0-9]+(?:\.[0-9]+)?)([smhd])?\b")
PY_SLEEP_RE = re.compile(r"\btime\.sleep\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*\)")
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
NOOP_RE = re.compile(
    r"(?:cat\s+/dev/null|\btrue\b|^\s*:\s*$|echo\s*[\"']{2}|sleep\s+[0-9.]+)"
)

REASON = """Blocked: unconditional `sleep {n}` — blind time-estimate waits are forbidden.
Wait on a CONDITION instead:
  orca terminal wait --terminal <h> --for tui-idle --timeout-ms <ms>
  orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 600000 --json
  until <check-cmd>; do sleep 30; done          # condition loop (allowed)
  ssh <host> 'until <remote-check>; do sleep 30; done'   # push the wait remote-side
  npx wait-on tcp:<port>                        # dev-server readiness
  wait-for '<check-cmd>' [--interval N] [--timeout N]   # ~/.local/bin/wait-for
Rule: sleep is only allowed as the interval INSIDE an until/while/for loop."""


PY_LOOP = re.compile(r"(?m)^\s*(?:while|for)\b")


def in_condition_loop(cmd: str, pos: int, shell: bool = True) -> bool:
    before = cmd[:pos]
    if not shell:
        # python: a preceding while/for line means the sleep is loop-bound
        return bool(PY_LOOP.search(before))
    opens = len(LOOP_OPEN.findall(before))
    closes = len(LOOP_CLOSE.findall(before))
    return opens > closes and bool(LOOP_CLOSE.search(cmd[pos:]))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    ti = data.get("tool_input") or {}
    cmd = ti.get("command") or ti.get("text_input") or ti.get("bytes_input") or ""
    if not cmd:
        return

    bad = []
    matches = [
        (m.start(), float(m.group(1)) * UNIT.get(m.group(2) or "s", 1), True)
        for m in SLEEP_RE.finditer(cmd)
    ] + [
        (m.start(), float(m.group(1)), False) for m in PY_SLEEP_RE.finditer(cmd)
    ]
    for pos, n, shell in matches:
        if in_condition_loop(cmd, pos, shell):
            continue
        if n >= MIN_BLOCK_S:
            bad.append(n)
        elif n >= WASTE_MIN_S:
            stripped = NOOP_RE.sub(" ", cmd)
            stripped = re.sub(r"[;&|]|&&|\|\|", " ", stripped).strip()
            if not stripped:
                bad.append(n)

    if bad:
        reason = REASON.format(n=int(max(bad)))
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
        sys.stderr.write(reason + "\n")
        sys.exit(2)


main()
