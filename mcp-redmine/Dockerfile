FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir mcp-redmine==2026.1.13.152335

# Wrapper který vypne DNS rebinding protection před startem mcp-redmine
COPY entrypoint.py /app/entrypoint.py

EXPOSE 8000

CMD ["python", "/app/entrypoint.py"]
