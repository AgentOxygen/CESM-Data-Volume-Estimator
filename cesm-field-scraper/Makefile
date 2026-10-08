IMAGE = cesm-field-scraper:cesm3_0_alpha09e

build:
	docker build -f docker/cesm3_0_alpha09e.Dockerfile -t $(IMAGE) .

run:
	mkdir -p out
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR)/out:/out" $(IMAGE)

test:
	docker run --rm -v "$(CURDIR):/tool" -w /tool -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
	    sh -c "pip install -q --root-user-action=ignore pyyaml==6.0.2 pytest==8.3.4 && pytest -q -p no:cacheprovider"
