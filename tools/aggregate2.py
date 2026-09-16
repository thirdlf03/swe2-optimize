import json, glob, os, re
from collections import Counter, defaultdict
from datetime import datetime

TDIR = os.path.expanduser('~/.local/share/devin/cli/transcripts')

cmd_patterns = {
 'git': re.compile(r'\bgit (status|diff|log|add|commit|push|checkout|worktree|pr|merge)'),
 'gh': re.compile(r'\bgh '),
 'test/lint/build': re.compile(r'\b(npm|pnpm|yarn|bun|pytest|vitest|jest|cargo|go test|ruff|mypy|tsc|make|docker)\b'),
 'ls/find exploration': re.compile(r'^\s*(ls|pwd|find|tree|cat|head|tail)\b'),
}
lang_ja = re.compile(r'[぀-ヿ一-鿿]')

per_model = defaultdict(lambda: Counter())
dur = defaultdict(list)
msg_lang = defaultdict(Counter)
think_lang = defaultdict(Counter)
sessions_full = []

for path in sorted(glob.glob(TDIR + '/*.json')):
    d = json.load(open(path))
    model = d.get('agent', {}).get('model_name', 'unknown')
    if not model.startswith('SWE-2'): continue
    steps = d['steps']
    ag = [s for s in steps if s['source'] == 'agent']
    if not ag: continue
    try:
        t0 = datetime.fromisoformat(steps[0]['timestamp']); t1 = datetime.fromisoformat(steps[-1]['timestamp'])
        dur[model].append((t1-t0).total_seconds()/60)
    except Exception: pass
    sessions_full.append((d['session_id'], model, len(ag)))
    for s in ag:
        for tc in (s.get('tool_calls') or []):
            if tc['function_name'] == 'exec':
                cmd = str((tc.get('arguments') or {}).get('command',''))
                for k, pat in cmd_patterns.items():
                    if pat.search(cmd): per_model[model][k] += 1
        msg = s.get('message') or ''
        rc = s.get('reasoning_content') or ''
        if msg.strip():
            msg_lang[model]['ja' if lang_ja.search(msg) else 'en/other'] += 1
        if rc.strip():
            think_lang[model]['ja' if lang_ja.search(rc) else 'en/other'] += 1

print("== exec command categories ==")
for m, c in per_model.items(): print(m, dict(c))
print("\n== session durations (min) ==")
for m, v in dur.items():
    v2 = sorted(v)
    print(f"{m}: n={len(v2)} median={v2[len(v2)//2]:.1f} mean={sum(v2)/len(v2):.1f} max={v2[-1]:.1f}")
print("\n== agent message language ==")
for m, c in msg_lang.items(): print(m, dict(c))
print("\n== reasoning language ==")
for m, c in think_lang.items(): print(m, dict(c))
