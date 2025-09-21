## Multistage build to keep runtime image small
# Base builder with full toolchain for SciPy/NumPy wheels if needed
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps for building some packages (scipy, numpy) and for voice
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    libopus0 \
    libopusfile0 \
    libpq-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY HacksterBot/requirements.txt ./requirements.txt

# Pre-install deps into a local directory to copy over later
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt


# Final runtime image
FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

# Runtime libs: opus for voice, fonts for CJK, and minimal tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopus0 \
    libopusfile0 \
    fonts-noto-cjk \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Use venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy project
COPY HacksterBot/ ./HacksterBot/

# Non-root user
RUN useradd -u 10001 -m appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose no network port (Discord uses outbound)
# HEALTHCHECK: verify the bot script is importable (fast sanity)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import sys; import importlib.util as u; sys.exit(0 if u.find_spec('HacksterBot.main') else 1)" || exit 1

# Default command: run the bot main
# Expect env vars via docker run --env-file
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "HacksterBot.main"]


