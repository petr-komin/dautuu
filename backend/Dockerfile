FROM python:3.12-slim

WORKDIR /app

# System deps pro asyncpg a bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Vytvoř non-root uživatele se stejným UID jako hostitelský uživatel (default 1000).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} appuser 2>/dev/null || true && \
    useradd -u ${APP_UID} -g ${APP_GID} -s /bin/sh -M appuser 2>/dev/null || true && \
    mkdir -p /workspace

# Entrypoint běží jako root — fixne ownership /workspace po bind-mountu
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Nespouštíme USER appuser zde — entrypoint to udělá sám přes exec su
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
