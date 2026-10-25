FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/scripts

WORKDIR /app

COPY gateway-v54g/requirements.txt /app/gateway-requirements.txt
RUN pip install --no-cache-dir -r /app/gateway-requirements.txt

COPY gateway-v54g /app/gateway
COPY scripts /app/scripts
COPY integration/orchestration /app/integration/orchestration

RUN mkdir -p /data

EXPOSE 8090
CMD ["sh", "-c", "exec uvicorn gateway.app:app --host ${APPLAB_V54G_BIND_HOST:-0.0.0.0} --port 8090"]
