# Offline preprocessing only; the root submission Dockerfile is unchanged.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY requirements.lock /opt/requirements.lock
RUN python -m pip install --no-cache-dir -r /opt/requirements.lock coverage==7.13.5
ENV PYTHONPATH=/src:/tool PYTHONDONTWRITEBYTECODE=1 SKIP_INTEGRATION=0 HOME=/tmp
WORKDIR /src
ENTRYPOINT ["python", "/tool/generate.py"]
