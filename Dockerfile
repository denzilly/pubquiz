FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Stdlib only -- no requirements.txt to install.
COPY server.py ./
COPY web ./web
COPY scrape ./scrape

# Pre-create data/ owned by the app user so the container can write scores.json
# and the scraped archive even without the compose bind mount. When ./data is
# mounted it takes over this path -- keep the host directory owned by your own
# uid (1000 on this single-user host), same as dinner/marketsarchive.
RUN useradd --create-home --uid 1000 pubquiz \
    && mkdir -p data \
    && chown -R pubquiz:pubquiz data

EXPOSE 8787
USER pubquiz

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8787/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
