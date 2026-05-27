"""CLI command: reki purge-file <path> — remove stale symbols for a deleted file."""
from __future__ import annotations

from pathlib import Path

import click


@click.command("purge-file")
@click.argument("file_path", type=click.Path())
@click.option("--db", default=None, help="Path to store.db (auto-detected if omitted).")
def purge_file_cmd(file_path: str, db: str | None) -> None:
    """Remove all symbols, wiki pages, and embeddings for FILE_PATH from the DB."""
    from rekipedia.storage.sqlite_store import SqliteStore

    # Auto-detect DB: walk up from file_path looking for .rekipedia/store.db
    if db is None:
        search = Path(file_path).resolve().parent
        while True:
            candidate = search / ".rekipedia" / "store.db"
            if candidate.exists():
                db = str(candidate)
                break
            parent = search.parent
            if parent == search:
                # Fall back to cwd
                db = str(Path.cwd() / ".rekipedia" / "store.db")
                break
            search = parent

    store = SqliteStore(db)
    store.open()
    try:
        run_id = store.get_latest_run_id(str(Path(file_path).resolve().parent))
        # Try various run_id resolutions
        if run_id is None:
            # Try from the file's repo root (walk up to find .rekipedia)
            search = Path(file_path).resolve().parent
            while True:
                candidate = search / ".rekipedia"
                if candidate.is_dir():
                    run_id = store.get_latest_run_id(str(search))
                    break
                parent = search.parent
                if parent == search:
                    break
                search = parent

        if run_id is None:
            click.echo(f"No scan run found for {file_path}. Nothing to purge.", err=True)
            return

        result = store.purge_file(run_id, file_path)
        click.echo(
            f"Purged {file_path!r} from run {run_id}: "
            f"{result['symbols']} symbols, {result['relationships']} relationships, "
            f"{result['pages']} pages, {result['files']} file records removed."
        )
    finally:
        store.close()
