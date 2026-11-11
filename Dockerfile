# API image: FastAPI, the pipeline and the synthetic corpus of one seed (generated at build time).
# Web client: deployed separately (Vercel, root directory `web`). See docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOST=0.0.0.0 PORT=8000
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[postgres]"

# the corpus the API serves (fact base, simulated news) is regenerated from the seed, never shipped
COPY data/synthetic/1234/truth ./data/synthetic/1234/truth
ARG SEED=1234
ENV SEED=${SEED}
RUN python -m ainma.synth generate --seed ${SEED} --out data/synthetic \
 && python -m ainma.synth verify data/synthetic/${SEED}

RUN useradd --create-home app && mkdir -p data/cache && chown -R app /app
USER app
EXPOSE 8000
CMD ["python", "-m", "ainma.api"]
