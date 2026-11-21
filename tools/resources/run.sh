#!/bin/sh
# Run from the repository root after the Stage 3 clean checkout is available.
set -eu
source_dir="$PWD/.local/coverage-final/sqlglot"
work_dir="${1:-$PWD/.local/stage5/resource-reproduction}"
mkdir -p "$work_dir"
work_dir="$(cd "$work_dir" && pwd)"
test ! -e "$work_dir/run.json"
test "$(git -C "$source_dir" rev-parse HEAD)" = eb11aec4be8cb2122afe713a4816662c3f0fb2fa
test -z "$(git -C "$source_dir" status --porcelain --untracked-files=all)"
docker build --platform linux/amd64 -f tools/coverage/Dockerfile -t blast-radius-coverage .
docker run --rm --platform linux/amd64 --network none --entrypoint python blast-radius-coverage \
  -c 'import json,platform,pytest; print(json.dumps(dict(platform=platform.platform(),python=platform.python_version(),pytest=pytest.__version__)))' \
  > "$work_dir/environment.json"
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 6g \
  --pids-limit 256 --read-only --tmpfs /tmp:rw,size=512m \
  --env PYTHONHASHSEED=0 --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
  --env MKL_NUM_THREADS=1 --env RESOURCE_ACCESS_TRACE=1 --env PYTHONPATH=/src:/access:/tool \
  --volume "$source_dir:/src:ro" --volume "$PWD/tools/coverage:/tool:ro" \
  --volume "$PWD/tools/resources:/access:ro" --volume "$PWD/sample/tests.json:/manifest/tests.json:ro" \
  --volume "$work_dir:/raw" --entrypoint python blast-radius-coverage /access/record.py
python3 tools/resources/export.py "$source_dir" sample/tests.json "$work_dir" coverage_index/resources.json
