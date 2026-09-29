from pathlib import Path

from docparse_service.storage import LocalObjectStorage


def test_local_put_and_get(tmp_path: Path):
    store = LocalObjectStorage(tmp_path)
    uri = store.put_bytes("tasks/t1/result/result.md", b"hello", "text/markdown")
    assert uri.startswith("local://")
    assert store.get_bytes("tasks/t1/result/result.md") == b"hello"
