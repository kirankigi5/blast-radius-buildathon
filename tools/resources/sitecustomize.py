"""Offline Python audit hook, inherited by spawned interpreters."""

import json
import os
import sys

context = "shared:child"
events = set()
is_parent = os.getpid() == 1
active = False


def hook(event, args):
    global active
    if active:
        return
    if event in {"subprocess.Popen", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec", "os.system"}:
        events.add(("process", event, context if is_parent else "shared:child"))
        return
    if event not in {"open", "os.listdir", "os.scandir", "glob.glob", "glob.glob/2", "pathlib.Path.glob", "pathlib.Path.rglob"}:
        return
    path = args[0]
    if path is None and event in {"os.listdir", "os.scandir"}:
        path = "."
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    active = True
    try:
        path = os.path.realpath(os.fsdecode(path))
        if path == "/src/tests/fixtures" or path.startswith("/src/tests/fixtures/"):
            events.add(("read" if event == "open" else "directory", path.removeprefix("/src/"),
                        context if is_parent else "shared:child"))
    finally:
        active = False


def flush():
    if not events:
        return
    with open(f"/raw/access-{os.getpid()}.json", "w") as stream:
        json.dump(sorted(events), stream, separators=(",", ":"))


if os.environ.get("RESOURCE_ACCESS_TRACE") == "1":
    import atexit
    atexit.register(flush)
    sys.addaudithook(hook)
