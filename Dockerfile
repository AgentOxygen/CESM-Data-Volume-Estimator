FROM python:3.12-slim

# Two dependencies, pinned. PyYAML because writing a YAML parser is not lazy;
# pytest because the data needs a safety net. Nothing else is needed -- the
# frontend has no build step and the dev server is python -m http.server.
RUN pip install --no-cache-dir pyyaml==6.0.2 pytest==8.3.4

WORKDIR /app
