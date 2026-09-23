FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APPLAB_FLOW_DIR=/app/flows
ENV APPLAB_TEST_OUTPUT_DIR=/tmp/applab-maestro
ENV PATH="/root/.maestro/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       adb bash ca-certificates curl default-jre-headless unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -Ls "https://get.maestro.mobile.dev" | bash

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY flows ./flows

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
