"""Cross-repo search — fan-out across multiple SQLite stores."""
from __future__ import annotations
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def _tokenize_symbol(name: str) -> list[str]:
    """Split camelCase and snake_case into tokens."""
    tokens = name.replace('-', '_').split('_')
    result = []
    for t in tokens:
        parts = re.sub(r'([A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)|[a-z]+|\d+)', r'\1 ', t).split()
        result.extend(p.lower() for p in parts if p)
    return result or [name.lower()]


def _compute_idf(all_symbols: list) -> dict[str, float]:
    """Compute BM25 IDF for each token across the full symbol corpus.

    IDF(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)

    where N = total symbol count, df(t) = number of symbols containing token t.
    Returns a dict mapping token → idf score.
    """
    N = len(all_symbols)
    if N == 0:
        return {}
    df: Counter[str] = Counter()
    for s in all_symbols:
        name = s.name if hasattr(s, 'name') else s.get('name', '')
        tokens = set(_tokenize_symbol(name))
        df.update(tokens)
    return {
        token: math.log((N - freq + 0.5) / (freq + 0.5) + 1)
        for token, freq in df.items()
    }


def _score_bm25(
    query_tokens: list[str],
    symbol_tokens: list[str],
    idf: dict[str, float],
) -> float:
    """BM25 scoring with per-corpus IDF weights."""
    k1, b, avgdl = 1.5, 0.75, 5.0
    dl = len(symbol_tokens)
    score = 0.0
    tf_map: dict[str, int] = {}
    for t in symbol_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        token_idf = idf.get(qt, 1.0)  # fallback to 1.0 for unseen tokens
        score += token_idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
    return score


def _search_single_repo(db_path: Path, query: str, kind: str | None = None) -> list[dict]:
    """Search symbols in one repo's DB. Returns list of match dicts."""
    try:
        from rekipedia.storage.sqlite_store import SqliteStore
        store = SqliteStore(db_path)
        run_id = store.latest_run_id()
        if not run_id:
            return []
        symbols = store.get_all_symbols(run_id)
        query_tokens = _tokenize_symbol(query)

        # Compute per-corpus IDF — rare tokens get higher weight
        idf = _compute_idf(symbols)

        results = []
        for s in symbols:
            name = s.name if hasattr(s, 'name') else s.get('name', '')
            file = s.file if hasattr(s, 'file') else s.get('file', '')
            sym_kind = s.kind if hasattr(s, 'kind') else s.get('kind', '')
            # Apply kind filter if specified
            if kind and sym_kind != kind:
                continue
            symbol_tokens = _tokenize_symbol(name)
            score = _score_bm25(query_tokens, symbol_tokens, idf)
            if score > 0:
                results.append({'name': name, 'file': file, 'kind': sym_kind, 'score': score, 'repo': str(db_path.parent.parent)})
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:50]
    except Exception:
        return []


def search_all_repos(query: str, repo_dirs: list[str] | None = None, kind: str | None = None) -> list[dict]:
    """Search all registered repos in parallel. Returns merged+ranked results."""
    if repo_dirs is None:
        from rekipedia.watcher.watcher import list_repos
        repo_dirs = list_repos()

    db_paths = []
    for repo in repo_dirs:
        db = Path(repo) / '.rekipedia' / 'rekipedia.db'
        if db.exists():
            db_paths.append(db)

    if not db_paths:
        return []

    all_results = []
    with ThreadPoolExecutor(max_workers=min(len(db_paths), 8)) as pool:
        futures = {pool.submit(_search_single_repo, db, query, kind): db for db in db_paths}
        for fut in as_completed(futures):
            all_results.extend(fut.result())

    all_results.sort(key=lambda x: x['score'], reverse=True)
    return all_results[:200]
