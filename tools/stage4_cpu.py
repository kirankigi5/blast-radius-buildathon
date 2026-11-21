"""Container-only CPU estimate; protocol stdout is left to the selector."""

import json
from pathlib import Path
import resource
import runpy
import sys
import time


def cpu_stat():
    try:
        return {key: int(value) for key, value in
                (line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())}
    except (OSError, ValueError):
        return {}


script = Path("/app/selector.py")
sys.path.insert(0, str(script.parent))
start = time.perf_counter()
runpy.run_path(str(script), run_name="__main__")
usage = resource.getrusage(resource.RUSAGE_SELF)
children = resource.getrusage(resource.RUSAGE_CHILDREN)
stat = cpu_stat()
print(json.dumps({
    "measurement": "container_cpu_snapshot",
    "process_user_seconds": usage.ru_utime,
    "process_system_seconds": usage.ru_stime,
    "process_cpu_seconds": usage.ru_utime + usage.ru_stime,
    "children_cpu_seconds": children.ru_utime + children.ru_stime,
    "cgroup_usage_seconds": stat.get("usage_usec", 0) / 1_000_000 if "usage_usec" in stat else None,
    "cgroup": Path("/proc/self/cgroup").read_text().strip(),
    "selector_invocation_wall_seconds": time.perf_counter() - start,
    "limitations": "Local Linux amd64 under ARM64 emulation; instrumented PID 1; snapshot excludes final printing/shutdown; not server scoring",
}), file=sys.stderr)
