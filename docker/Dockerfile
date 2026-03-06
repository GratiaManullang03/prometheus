FROM python:3.12-slim

LABEL maintainer="prometheus-agent"
LABEL description="Isolated experiment container for Prometheus self-improving agent"

# Security: run as non-root
RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /workspace

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ /workspace/

# Install Python dependencies if requirements.txt exists
RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# Switch to non-root user
USER agent

# Default: run test suite
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
