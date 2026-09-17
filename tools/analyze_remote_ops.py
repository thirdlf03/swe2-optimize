#!/usr/bin/env python3
"""Transcripts を走査し、sleep・shell file-ops・リモート書き込みを検出する。

- sleep: exec/write_to_process 内の `sleep N`（累計秒数つき）
- file-ops: `hooks/no_shell_file_ops.py` の classify() をそのまま適用
  （hook 導入前環境の行動を「導入されていたらブロックされていた」として測る）
- remote-write: git push / gh 書き込み系 / gh api 変異（POST・mutation 等）を
  直前のユーザー発言とセットで列挙（承認有無の目視確認用）

使い方: python3 tools/analyze_remote_ops.py
"""
import json, re, glob, importlib.util, os
from collections import Counter

TDIR = os.path.expanduser('~/.local/share/devin/cli/transcripts')
NSFO_PATH = os.path.join(os.path.dirname(__file__), '..', 'hooks', 'no_shell_file_ops.py')
spec = importlib.util.spec_from_file_location('nsfo', NSFO_PATH)
nsfo = importlib.util.module_from_spec(spec); spec.loader.exec_module(nsfo)

SLEEP_RE = re.compile(r"\bsleep\s+([0-9]+(?:\.[0-9]+)?)([smhd])?\b")
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}

REMOTE_WRITE_PATTERNS = [
    ('git push', re.compile(r"\bgit\s+push\b")),
    ('gh pr create', re.compile(r"\bgh\s+pr\s+create\b")),
    ('gh pr review', re.compile(r"\bgh\s+pr\s+review\b")),
    ('gh pr merge', re.compile(r"\bgh\s+pr\s+merge\b")),
    ('gh pr edit', re.compile(r"\bgh\s+pr\s+edit\b")),
    ('gh pr close/comment', re.compile(r"\bgh\s+pr\s+(close|comment|ready|reopen)\b")),
    ('gh issue write', re.compile(r"\bgh\s+issue\s+(create|edit|close|comment|delete)\b")),
    ('gh api -X mutation', re.compile(r"\bgh\s+api\b[^|;&]*?(-X\s*(POST|PUT|PATCH|DELETE)|--method\s+(POST|PUT|PATCH|DELETE))")),
    ('gh api graphql mutation', re.compile(r"\bgh\s+api\s+graphql\b[^|;&]*?mutation")),
    ('gh release', re.compile(r"\bgh\s+release\s+(create|edit|delete|upload)\b")),
    ('gh repo write', re.compile(r"\bgh\s+repo\s+(create|edit|delete|fork)\b")),
    ('gh api replies/resolve', re.compile(r"\bgh\s+api\b[^|;&]*?/comments/\d+/replies")),
]

for path in sorted(glob.glob(f'{TDIR}/*.json')):
    d = json.load(open(path))
    sid = d['session_id']
    model = d.get('agent', {}).get('model_name', '?')
    steps = d['steps']
    print(f"\n{'='*70}\n# {sid} ({model})")

    sleeps, fileops, writes = [], [], []
    last_user_msg = ''
    for s in steps:
        if s['source'] == 'user':
            m = s.get('message')
            if isinstance(m, str):
                last_user_msg = m[:160].replace('\n', ' ')
            elif isinstance(m, list):
                last_user_msg = ' '.join(
                    str(x.get('text', ''))[:160] for x in m if isinstance(x, dict)
                ).replace('\n', ' ')[:160]
            continue
        if s['source'] != 'agent':
            continue
        for tc in s.get('tool_calls') or []:
            fn = tc['function_name']
            args = tc.get('arguments') or {}
            cmd = args.get('command') or args.get('text_input') or ''
            if fn in ('exec', 'write_to_process') and cmd:
                for m in SLEEP_RE.finditer(cmd):
                    n = float(m.group(1)) * UNIT.get(m.group(2) or 's', 1)
                    sleeps.append((n, cmd[:110]))
                hits = nsfo.classify(cmd)
                if hits:
                    fileops.append((hits[0][0], cmd[:110]))
                for label, rx in REMOTE_WRITE_PATTERNS:
                    if rx.search(cmd):
                        writes.append((label, cmd[:130], last_user_msg))
                        break

    if sleeps:
        print(f"  SLEEPS: {len(sleeps)} calls, {sum(n for n,_ in sleeps):.0f}s total")
        for n, c in sleeps: print(f"    {n:>6.0f}s  {c}")
    if fileops:
        print(f"  SHELL FILE OPS (hook would block): {dict(Counter(k for k,_ in fileops))} total={len(fileops)}")
        for k, c in fileops[:12]: print(f"    [{k}] {c}")
    if writes:
        print(f"  REMOTE WRITES: {len(writes)}")
        for l, c, um in writes:
            print(f"    [{l}] {c}\n        user-prev: {um!r}")
