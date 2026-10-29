import threading
from pathlib import Path

from docflow.fsutil import write_atomic


def test_two_writers_of_the_same_file_never_share_a_temporary_file(tmp_path, monkeypatch):
    # DOC534.51: the temporary file was always "<name>.tmp": one writer could swap in, or delete, the other's
    target = tmp_path / "index.json"
    real_replace, sources = Path.replace, []

    def spy(self, destination):
        sources.append(self.name)
        return real_replace(self, destination)
    monkeypatch.setattr(Path, "replace", spy)
    write_atomic(target, "one")
    write_atomic(target, "two")
    assert len(set(sources)) == 2 and all(s.startswith("index.json.") and s.endswith(".tmp") for s in sources)
    assert target.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["index.json"]                  # no temporary file is left behind


def test_the_data_is_synced_before_the_swap_and_the_folder_after_it(tmp_path, monkeypatch):
    # DOC534.181: no fsync, so after a power cut the rename could be on the disk and the data not: an empty or truncated target
    import os
    import stat
    target = tmp_path / "index.json"
    events, real_fsync, real_replace = [], os.fsync, Path.replace

    def fsync(fd):
        events.append("fsync-folder" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        return real_fsync(fd)

    def replace(self, destination):
        events.append("replace")
        return real_replace(self, destination)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)
    write_atomic(target, "text")
    assert events[:2] == ["fsync-file", "replace"]                                     # the data first, then the swap
    if os.name != "nt":
        assert events == ["fsync-file", "replace", "fsync-folder"]                     # and the swap itself made durable
    assert target.read_text(encoding="utf-8") == "text" and [p.name for p in tmp_path.iterdir()] == ["index.json"]


def test_a_failed_write_leaves_the_old_text_and_no_temporary_file(tmp_path, monkeypatch):
    import os

    import pytest
    target = tmp_path / "index.json"
    write_atomic(target, "old")
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        write_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "old" and [p.name for p in tmp_path.iterdir()] == ["index.json"]


def test_concurrent_writers_leave_one_complete_text_and_no_temporary_file(tmp_path):
    target = tmp_path / "index.json"
    texts = [f"writer {n} " * 20000 for n in range(8)]
    errors = []

    def write(text):
        try:
            for _ in range(10):
                write_atomic(target, text)
        except OSError as e:                                                         # a missing temporary file was the symptom
            errors.append(e)
    threads = [threading.Thread(target=write, args=(t,)) for t in texts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and target.read_text(encoding="utf-8") in texts                # never a mix of two writers
    assert [p.name for p in tmp_path.iterdir()] == ["index.json"]
