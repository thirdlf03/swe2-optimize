import json, glob, os, re
from collections import Counter, defaultdict

TDIR = os.path.expanduser('~/.local/share/devin/cli/transcripts')
OUT = '/tmp/swe2_analysis'

stats = {}
tool_freq = defaultdict(Counter)
tool_seqs = defaultdict(list)
parallel_calls = defaultdict(list)  # model -> list of tools-per-step counts
reasoning_chars = defaultdict(int)
msg_chars = defaultdict(int)
agent_steps = defaultdict(int)
user_prompts = defaultdict(list)
sessions_meta = []
error_signs = Counter()

for path in sorted(glob.glob(TDIR + '/*.json')):
    d = json.load(open(path))
    model = d.get('agent', {}).get('model_name', 'unknown')
    if not model.startswith('SWE-2'):
        continue
    sid = d['session_id']
    steps = d['steps']
    n_user = sum(1 for s in steps if s['source'] == 'user')
    ag = [s for s in steps if s['source'] == 'agent']
    n_agent = len(ag)
    t0 = steps[0]['timestamp'] if steps else None
    t1 = steps[-1]['timestamp'] if steps else None
    sessions_meta.append(dict(sid=sid, model=model, steps=len(steps),
                              user=n_user, agent=n_agent, t0=t0, t1=t1))
    digest = [f"# {sid} ({model})"]
    for s in steps:
        if s['source'] == 'user':
            m = s['message']
            user_prompts[model].append(m[:200])
            digest.append(f"\n## USER: {m[:500]}")
        elif s['source'] == 'agent':
            agent_steps[model] += 1
            rc = s.get('reasoning_content') or ''
            reasoning_chars[model] += len(rc)
            msg = s.get('message') or ''
            msg_chars[model] += len(msg)
            tcs = s.get('tool_calls') or []
            parallel_calls[model].append(len(tcs))
            names = []
            for tc in tcs:
                fn = tc['function_name']
                tool_freq[model][fn] += 1
                names.append(fn)
                args = tc.get('arguments') or {}
                # capture command/edit targets briefly
                if fn == 'exec':
                    names[-1] += ':' + str(args.get('command',''))[:80]
                elif fn in ('read','edit','write'):
                    names[-1] += ':' + str(args.get('file_path',''))[-60:]
            tool_seqs[model].extend(names)
            obs = s.get('observation') or {}
            res = obs.get('results') or []
            err = any('error' in str(r.get('content',''))[:200].lower() or r.get('is_error') for r in res)
            line = f"AGENT: {msg[:300]}"
            if rc:
                line += f"\n  THINK: {rc[:400]}"
            if names:
                line += f"\n  TOOLS[{len(names)}]: {' | '.join(names[:10])}"
            if err:
                line += "  <--TOOL_ERROR"
                error_signs[model] += 1
            digest.append(line)
    with open(f'{OUT}/digests/{sid}.txt', 'w') as f:
        f.write('\n'.join(digest))

print("== sessions per model ==")
mc = Counter(m['model'] for m in sessions_meta)
print(mc)
print("\n== agent steps / reasoning chars / msg chars ==")
for m in mc:
    print(f"{m}: steps={agent_steps[m]}, reasoning_chars={reasoning_chars[m]} (avg {reasoning_chars[m]//max(agent_steps[m],1)}/step), msg_chars={msg_chars[m]} (avg {msg_chars[m]//max(agent_steps[m],1)}/step)")
print("\n== tool freq by model ==")
for m, c in tool_freq.items():
    print(f"\n{m}: total={sum(c.values())}")
    for k, v in c.most_common(20):
        print(f"  {k}: {v}")
print("\n== parallel tool calls distribution (count of tools in one step) ==")
for m, lst in parallel_calls.items():
    c = Counter(lst)
    multi = sum(v for k, v in c.items() if k > 1)
    print(f"{m}: {dict(sorted(c.items()))} | multi-tool steps={multi} ({100*multi//max(len(lst),1)}%)")
print("\n== tool errors observed ==")
print(dict(error_signs))
