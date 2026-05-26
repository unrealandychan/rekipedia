from pathlib import Path


def test_add_list_remove_repo(tmp_path, monkeypatch):
    config_file = tmp_path / "watch.json"
    monkeypatch.setattr("rekipedia.watcher.watcher.CONFIG_PATH", config_file)
    # Re-patch in module
    import importlib

    from rekipedia.watcher import watcher
    importlib.reload(watcher)
    monkeypatch.setattr(watcher, "CONFIG_PATH", config_file)

    repo = str(tmp_path / "myrepo")
    Path(repo).mkdir()

    watcher.add_repo(repo)
    assert repo in watcher.list_repos()

    watcher.remove_repo(repo)
    assert repo not in watcher.list_repos()

def test_add_duplicate(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "watch.json"
    import importlib

    from rekipedia.watcher import watcher
    importlib.reload(watcher)
    monkeypatch.setattr(watcher, "CONFIG_PATH", config_file)
    repo = str(tmp_path / "repo2")
    Path(repo).mkdir()
    watcher.add_repo(repo)
    watcher.add_repo(repo)  # duplicate
    assert watcher.list_repos().count(repo) == 1
