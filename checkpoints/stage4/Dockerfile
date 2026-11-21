# The scorer builds this on linux/amd64 and runs it with no network. The
# digest is the image we labeled every commit in: its Python and SQLite
# decide which sqlglot tests run, so keep it if your image runs them.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY coverage_index /app/coverage_index
COPY tools/fetch_base.py /tmp/fetch_base.py
RUN python /tmp/fetch_base.py /app/base /app/coverage_index/index.json && rm /tmp/fetch_base.py
COPY selector.py selection.py patch_analysis.py /app/
CMD ["python", "/app/selector.py"]
