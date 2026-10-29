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
