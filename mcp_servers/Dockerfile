FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sre_mcp ./sre_mcp
ENV PYTHONUNBUFFERED=1 SERVICE_MAP_PATH=/config/services.yaml
USER 10001
# Override the module per service in docker-compose, e.g. sre_mcp.servicenow
CMD ["python", "-m", "sre_mcp.servicenow", "--transport", "http"]
