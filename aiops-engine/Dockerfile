FROM python:3.10-slim

WORKDIR /app

# Install system dependencies and security updates, including curl and kubectl
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -LO "https://dl.k8s.io/release/v1.31.4/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel jaraco.context \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Grant read/write permissions to non-root user 10001 for S3 model downloads
RUN chown -R 10001:10001 /app

# Expose port 8000
EXPOSE 8000

# Set environment variable defaults
ENV AIOPS_SIMULATION_MODE=false
ENV PORT=8000

# Start Uvicorn server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
