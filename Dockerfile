FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY pyproject.toml README.md ./
COPY radicalize ./radicalize/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV RADICALIZE_DATA=/data/calendar

EXPOSE 8090

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["run"]
