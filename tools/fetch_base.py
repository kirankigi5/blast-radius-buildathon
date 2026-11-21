"""Build-only download of clean Python source; validate against the pinned index."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import urllib.request

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
ARCHIVE_SHA256 = "93b2445f15f395b81c20556777ece19a6c7507df950f13fa9fac4a3be739af0d"


def main():
    destination = Path(sys.argv[1])
    index = json.loads(Path(sys.argv[2]).read_text())
    assert index["source_revision"] == REVISION
    resources_path = Path(sys.argv[2]).with_name("resources.json")
    files = dict(index["files"])
    if resources_path.is_file():
        resources = json.loads(resources_path.read_text())
        assert resources["source_revision"] == REVISION
        files.update(resources["files"])
    with urllib.request.urlopen(f"https://codeload.github.com/tobymao/sqlglot/tar.gz/{REVISION}", timeout=90) as response:
        archive_bytes = response.read()
    assert hashlib.sha256(archive_bytes).hexdigest() == ARCHIVE_SHA256
    found = set()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive:
            path = Path(*Path(member.name).parts[1:])
            name = path.as_posix()
            if name not in files:
                continue
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            content = archive.extractfile(member).read()
            assert hashlib.sha256(content).hexdigest() == files[name]["sha256"], name
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            found.add(name)
    assert found == set(files)
    (destination / "REVISION").write_text(REVISION + "\n")


if __name__ == "__main__":
    main()
