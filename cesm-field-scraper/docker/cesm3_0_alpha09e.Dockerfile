# cesm-field-scraper, pinned to CESM tag cesm3_0_alpha09e. This file is the
# provenance record for the YAML it produces.
#
#   docker build -f docker/cesm3_0_alpha09e.Dockerfile -t cesm-field-scraper:cesm3_0_alpha09e .
#   docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/out:/out" cesm-field-scraper:cesm3_0_alpha09e
#
# Writes /out/<component>.yaml plus /out/submodules.txt (every external's commit).

FROM python:3.12 AS source
ENV CESM_TAG=cesm3_0_alpha09e
RUN git clone --quiet --depth 1 --branch $CESM_TAG https://github.com/ESCOMP/CESM.git /cesm \
 && test "$(git -C /cesm rev-parse HEAD)" = 7887191040022e2629d17ff44d4270c89d1a9dbe
WORKDIR /cesm
# `git submodule status --recursive` would be the natural inventory, but
# CISM carries a stale gitlink (libraries/mct) that makes it abort.
RUN ./bin/git-fleximod update cam clm cice mom cism mosart \
 && find . -name .git | sort | while read g; do d=${g%/.git}; \
      echo "$(git -C $d rev-parse HEAD) $d $(git -C $d describe --tags --always)"; done > submodules.txt \
 && find . -name .git -prune -exec rm -rf {} +

FROM python:3.12-slim
RUN pip install --no-cache-dir pyyaml==6.0.2
ENV CESM_TAG=cesm3_0_alpha09e PYTHONPATH=/opt PYTHONDONTWRITEBYTECODE=1
COPY --from=source /cesm /cesm
COPY cesm_fields /opt/cesm_fields
ENTRYPOINT ["sh", "-c", "cp /cesm/submodules.txt /out/ && python -m cesm_fields /cesm /out"]
