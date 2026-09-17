import re
from collections import Counter, defaultdict
from datetime import datetime
from _common import transcript_paths, load_json, parallel_map

cmd_patterns = {
 'git': re.compile(r'\bgit (status|diff|log|add|commit|push|checkout|worktree|pr|merge)'),
 'gh': re.compile(r'\bgh '),
 'test/lint/build': re.compile(r'\b(npm|pnpm|yarn|bun|pytest|vitest|jest|cargo|go test|ruff|mypy|tsc|make|docker)\b'),
 'ls/find exploration': re.compile(r'^\s*(ls|pwd|find|tree|cat|head|tail)\b'),
}
lang_ja = re.compile(r'[぀-ヿ一-鿿]')


def analyze_file(path):
    d = load_json(path)
    model = d.get('agent', {}).get('model_name', 'unknown')
    if not model.startswith('SWE-2'):
        return None
    steps = d['steps']
    ag = [s for s in steps if s['source'] == 'agent']
    if not ag:
        return None

    dur_min = None
    try:
        t0 = datetime.fromisoformat(steps[0]['timestamp'])
        t1 = datetime.fromisoformat(steps[-1]['timestamp'])
        dur_min = (t1 - t0).total_seconds() / 60
    except Exception:
        pass

    cmds = Counter()
    msg_lang = Counter()
    think_lang = Counter()
    for s in ag:
        for tc in (s.get('tool_calls') or []):
            if tc['function_name'] == 'exec':
                cmd = str((tc.get('arguments') or {}).get('command',''))
                for k, pat in cmd_patterns.items():
                    if pat.search(cmd): cmds[k] += 1
        msg = s.get('message') or ''
        rc = s.get('reasoning_content') or ''
        if msg.strip():
            msg_lang['ja' if lang_ja.search(msg) else 'en/other'] += 1
        if rc.strip():
            think_lang['ja' if lang_ja.search(rc) else 'en/other'] += 1

    return dict(model=model, sid=d['session_id'], n_agent=len(ag),
                dur_min=dur_min, cmds=cmds, msg_lang=msg_lang,
                think_lang=think_lang)


def main():
    per_model = defaultdict(lambda: Counter())
    dur = defaultdict(list)
    msg_lang = defaultdict(Counter)
    think_lang = defaultdict(Counter)
    sessions_full = []

    for r in parallel_map(analyze_file, transcript_paths()):
        if r is None:
            continue
        m = r['model']
        if r['dur_min'] is not None:
            dur[m].append(r['dur_min'])
        sessions_full.append((r['sid'], m, r['n_agent']))
        per_model[m].update(r['cmds'])
        msg_lang[m].update(r['msg_lang'])
        think_lang[m].update(r['think_lang'])

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


if __name__ == '__main__':
    main()
