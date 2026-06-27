FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROOFALPHA_MODE=paper \
    PROOFALPHA_TELEMETRY=off \
    PROOFALPHA_LOG_DIR=/tmp/proofalpha/logs

RUN useradd --create-home --uid 10001 proofalpha
WORKDIR /app

COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src ./src
COPY examples ./examples
COPY skills ./skills

RUN python -m pip install --upgrade pip && python -m pip install .

USER proofalpha
ENTRYPOINT ["proofalpha"]
CMD ["doctor", "--format", "json"]
