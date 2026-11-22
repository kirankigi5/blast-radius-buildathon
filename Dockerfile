# The scorer builds this on linux/amd64 and runs it with no network. The
# digest is the image we labeled every commit in: its Python and SQLite
# decide which sqlglot tests run, so keep it if your image runs them.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# Test requirements, so the selector can run candidate tests at runtime.
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && rm /tmp/requirements.lock
COPY coverage_index /app/coverage_index
COPY tools/fetch_base.py /tmp/fetch_base.py
# /app/base: hashed files the static analysis reads. /app/src: the full pinned
# sqlglot tree (source, tests and fixtures) used as the overlay base for test runs.
RUN python /tmp/fetch_base.py /app/base /app/coverage_index/index.json /app/src && rm /tmp/fetch_base.py \
 && python -m compileall -q -j 0 /app/src/sqlglot /app/src/tests > /dev/null \
 && chmod -R a+rX /app
COPY selector.py selection.py patch_analysis.py declarations.py verify.py tpc_probe.py /app/
# Clean-tree fingerprints and execution-time functions for the TPC executor probe.
RUN cd /app/src && python /app/tpc_probe.py build /app/src /app/tpc_base.pkl \
 && python -m compileall -q /app/selector.py /app/selection.py /app/patch_analysis.py \
    /app/declarations.py /app/verify.py /app/tpc_probe.py && chmod -R a+rX /app
CMD ["python", "/app/selector.py"]
