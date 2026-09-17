#!/usr/bin/env python3
"""hook_recheck.py — sessions.db の tool_call_state を hook 判定ロジックで再分類する。

transcripts は ~100件でローテートされ古い分が消えるが、tool_call_state は
全セッションの rawInput + 実行結果(status: completed/failed)を保持する。
hook の違反判定を DB に対して再実行し、「実行まで至った違反」と
「ブロックされた未遂」を分離して集計する。

使い方:
    python3 tools/hook_recheck.py [HOOK_TS_EPOCH]

HOOK_TS_EPOCH を省略すると hooks/ 内ファイルの最古 mtime を使う
(=「それ以降に作られたセッションは hook 有効のはず」という era 分割)。
"""
import json, os, re, sqlite3, sys
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'hooks'))
import no_shell_file_ops as fo
import no_blind_sleep as bs

DB = os.path.expanduser('~/.local/share/devin/cli/sessions.db')
HOOK_TS = int(sys.argv[1]) if len(sys.argv) > 1 else int(min(
    os.path.getmtime(os.path.join(HERE, '..', 'hooks', f))
    for f in os.listdir(os.path.join(HERE, '..', 'hooks')) if f.endswith('.py')))


def blind_secs(cmd):
    """コマンド中の「hook がブロックするはずの sleep」の秒数リスト。"""
    cmd2 = bs.strip_heredocs(cmd)
    bad = []
    for m in bs.SLEEP_RE.finditer(cmd2):
        pos, n = m.start(), float(m.group(1)) * bs.UNIT.get(m.group(2) or 's', 1)
        if bs.in_data_literal(cmd2, pos) or bs.in_condition_loop(cmd2, pos, True):
            continue
        if n >= bs.MIN_BLOCK_S:
            bad.append(n)
        elif n >= bs.WASTE_MIN_S:
            stripped = bs.NOOP_RE.sub(' ', cmd2)
            stripped = re.sub(r'[;&|]|&&|\|\|', ' ', stripped).strip()
            if not stripped:
                bad.append(n)
    return bad


def all_sleep_secs(cmd):
    return sum(float(m.group(1)) * bs.UNIT.get(m.group(2) or 's', 1)
               for m in bs.SLEEP_RE.finditer(bs.strip_heredocs(cmd)))


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro&immutable=1', uri=True)
    meta = {r[0]: dict(wd=r[1] or '', model=r[2] or '', title=r[3] or '', created=r[4])
            for r in con.execute(
                'select id, working_directory, model, title, created_at from sessions')}

    def role(m):
        if '/orca/workspaces/' in m['wd']:
            leaf = m['wd'].rstrip('/').rsplit('/', 1)[-1]
            return 'worker-integ/review' if leaf.startswith(('integ', 'review')) else 'worker'
        t = m['title'].lower()
        return 'coordinator' if ('coordinator' in t or 'コーディネーター' in t) else 'interactive'

    S = defaultdict(lambda: defaultdict(float))
    exec_violations = []  # (sid, role, kind, secs_or_hits, cmd)

    for sid, j, ju in con.execute(
            'select session_id, tool_call_json, tool_call_update_json from tool_call_state'):
        m = meta.get(sid)
        if not m or not j:
            continue
        try:
            tc = json.loads(j)
        except Exception:
            continue
        if tc.get('kind') != 'execute':
            continue
        cmd = (tc.get('rawInput') or {}).get('command') or ''
        if not cmd:
            continue
        b = ('post' if m['created'] >= HOOK_TS else 'pre', role(m))
        rejected = bool(ju and 'Tool rejected' in ju)
        S[b]['exec'] += 1
        S[b]['sleep_s'] += all_sleep_secs(cmd)
        bad = blind_secs(cmd)
        hits = fo.classify(cmd)
        if bad:
            k = 'blind_blk' if rejected else 'blind_run'
            S[b][k + '_cmds'] += 1
            S[b][k + '_s'] += sum(bad)
            if not rejected:
                exec_violations.append((sid, b, 'sleep', sum(bad), cmd[:90]))
        if hits:
            k = 'fop_blk' if rejected else 'fop_run'
            S[b][k] += 1
            if not rejected:
                exec_violations.append((sid, b, 'fileop', len(hits), cmd[:90]))
        if re.search(r'\borca\b|\borch\b', cmd):
            S[b]['orca'] += 1

    print(f"era boundary: {datetime.fromtimestamp(HOOK_TS)}")
    print(f"{'bucket':<26}{'exec':>6}{'slpM':>7} | blind: {'run':>4}{'min':>6}{'blk':>4} | fileop: {'run':>4}{'blk':>4} | orca")
    for b in sorted(S):
        a = S[b]
        print(f"{'/'.join(b):<26}{a['exec']:>6.0f}{a['sleep_s']/60:>7.1f} |       "
              f"{a['blind_run_cmds']:>4.0f}{a['blind_run_s']/60:>6.1f}{a['blind_blk_cmds']:>4.0f} |        "
              f"{a['fop_run']:>4.0f}{a['fop_blk']:>4.0f} | {a['orca']:.0f}")

    post = [v for v in exec_violations if meta[v[0]]['created'] >= HOOK_TS]
    print(f"\n== EXECUTED violations in sessions started after boundary: {len(post)} ==")
    for sid, b, kind, n, cmd in post:
        print(f"  {sid:<22}{'/'.join(b):<22}{kind:<7}{cmd}")


if __name__ == '__main__':
    main()
