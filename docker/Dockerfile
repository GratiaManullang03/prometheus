FROM python:3.12-slim

LABEL maintainer="prometheus-agent"
LABEL description="Isolated self-improvement experiment container for Prometheus"

# Security: run as non-root
RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /workspace

# Copy Prometheus source into container
COPY src/ /workspace/

# Install core dependencies (skip playwright browser binary — not needed for unit tests)
RUN pip install --no-cache-dir \
    openai>=1.40.0 \
    httpx>=0.27.0 \
    pyyaml>=6.0.2 \
    python-dotenv>=1.0.0 \
    pytest>=8.0.0 \
    pytest-asyncio>=0.23.0 \
    && pip install --no-cache-dir playwright>=1.40.0 || true

# Switch to non-root user
USER agent

# Default: run Prometheus test suite
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
