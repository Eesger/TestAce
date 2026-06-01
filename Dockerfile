FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install hatchling
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
COPY --from=builder /install /usr/local
RUN useradd -m archiver
WORKDIR /data
USER archiver
CMD ["python", "-m", "xarchiver.scheduler"]
