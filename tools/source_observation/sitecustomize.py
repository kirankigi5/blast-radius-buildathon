"""Offline audit of source reads and code/position observers in clean pytest runs."""

import json
import os
import sys

context = "shared:collection"
parent = os.getpid()
seen = set()
active = False


def project_source(path):
    if isinstance(path, (str, bytes)):
        name = os.fsdecode(path)
        if name.endswith(".py"):
            path = os.path.realpath(name)
            if path.startswith("/src/sqlglot/"):
                return path.removeprefix("/src/")
    return None


def inside_import_loader():
    frame = sys._getframe(1)
    reading_code = False
    while frame:
        code = frame.f_code
        if code.co_filename == "<frozen importlib._bootstrap_external>":
            if code.co_name == "get_source":
                return False
            reading_code |= code.co_name == "get_code"
        elif reading_code:
            return True
        frame = frame.f_back
    return reading_code


def hook(event, args):
    global active
    if active or event not in {"open", "object.__getattr__"}:
        return
    active = True
    try:
        if event == "open":
            path = project_source(args[0])
            if not path or inside_import_loader():
                return
            kind = "source_read"
        else:
            obj, attr = args
            if attr == "__code__":
                code = obj.__code__
            elif attr == "f_code":
                code = obj.f_code
            elif attr == "tb_frame":
                code = obj.tb_frame.f_code
            else:
                return
            path = project_source(code.co_filename)
            if not path:
                return
            kind = attr
        pid = os.getpid()
        # PID 1 owns pytest's contexts. Spawned and forked readers do not.
        owner = context if pid == parent == 1 else "shared:child"
        entry = (kind, path, owner)
        if (pid, entry) not in seen:
            seen.add((pid, entry))
            with open(f"/result/observers-{pid}.jsonl", "a", encoding="utf-8") as out:
                out.write(json.dumps(entry) + "\n")
    finally:
        active = False


if os.environ.get("SOURCE_OBSERVATION_TRACE") == "1":
    sys.addaudithook(hook)
