import glob, json, os
from multiprocessing import get_context

TDIR = os.path.expanduser('~/.local/share/devin/cli/transcripts')


def transcript_paths(tdir=TDIR):
    return sorted(glob.glob(os.path.join(tdir, '*.json')))


def load_json(path):
    # bytes のまま loads するとテキスト層の decode を省けて速い
    with open(path, 'rb') as f:
        return json.loads(f.read())


def parallel_map(fn, items, workers=8):
    """fork Pool で items を並列処理。使えない環境では逐次にフォールバック。"""
    if len(items) <= 1:
        return [fn(x) for x in items]
    try:
        ctx = get_context('fork')
    except ValueError:
        return [fn(x) for x in items]
    n = min(workers, os.cpu_count() or 4, len(items))
    with ctx.Pool(n) as pool:
        return pool.map(fn, items)
