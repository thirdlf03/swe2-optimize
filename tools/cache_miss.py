from collections import Counter
from _common import transcript_paths, load_json, parallel_map

# "full-prefix miss" = agent step whose cached_tokens < 90% of the previous
# agent step's prompt_tokens. cached ~= static system prefix (~8-11K tok) means
# nearly the whole conversation was reprocessed uncached.


def analyze_file(path):
    d = load_json(path)
    model = d.get('agent', {}).get('model_name', '')
    if not model.startswith('SWE-2'):
        return None
    sid = d['session_id']
    prev_p = 0
    prev_src = None
    misses = 0
    steps = 0
    miss_sizes = []
    trigger = Counter()
    for s in d['steps']:
        if s['source'] == 'agent':
            m = s.get('metrics') or {}
            p = m.get('prompt_tokens', 0)
            c = m.get('cached_tokens', 0)
            if p:
                steps += 1
                if prev_p and c < prev_p * 0.9:
                    misses += 1
                    miss_sizes.append(p - c)
                    trigger[prev_src] += 1
                prev_p = p
        if s['source'] in ('user', 'system'):
            prev_src = s['source']
    return (sid, model, misses, steps, miss_sizes, trigger)


def main():
    rows = []
    miss_sizes = []
    trigger = Counter()

    for r in parallel_map(analyze_file, transcript_paths()):
        if r is None:
            continue
        sid, model, misses, steps, ms, tr = r
        rows.append((sid, model, misses, steps))
        miss_sizes.extend(ms)
        trigger.update(tr)

    total_miss = sum(r[2] for r in rows)
    total_uncached_in_miss = sum(miss_sizes)
    with_miss = sum(1 for r in rows if r[2])

    print(f"sessions: {len(rows)}  (with >=1 miss: {with_miss})")
    print(f"miss events: {total_miss}  uncached-in-miss tokens: {total_uncached_in_miss:,}")
    if miss_sizes:
        ms = sorted(miss_sizes)
        print(f"miss size: median={ms[len(ms)//2]:,} mean={total_uncached_in_miss//len(ms):,} max={ms[-1]:,}")
    print("\ntrigger (source of the step immediately before the miss):")
    for k, v in trigger.most_common():
        print(f"  after {k}: {v}")

    print("\nworst sessions (misses/agent-steps):")
    for sid, model, m, s in sorted(rows, key=lambda x: -(x[2] / max(x[3], 1)))[:15]:
        print(f"  {sid:24} {model:13} {m}/{s}")


if __name__ == '__main__':
    main()
