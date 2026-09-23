FROM python:3.12-slim

ARG EMULATOR_SCRIPTS_REF=0654f694b46794fae4b178f1e1a17cb60c5d2d34

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APPLAB_FLOW_DIR=/app/flows
ENV APPLAB_TEST_OUTPUT_DIR=/tmp/applab-maestro
ENV APPLAB_DATA_DIR=/data
ENV ADB_VENDOR_KEYS=/data
ENV PATH="/root/.maestro/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       adb bash ca-certificates curl default-jre-headless git unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -Ls "https://get.maestro.mobile.dev" | bash

# Install Google's current Python WebRTC signaling gateway. The gateway build
# generates its protobuf stubs from the Android Emulator AEMU proto sources.
RUN mkdir -p /opt/aemu-root/hardware/google \
    && git clone --depth 1 --branch emu-main-dev --filter=blob:none --sparse \
       https://android.googlesource.com/platform/hardware/google/aemu \
       /opt/aemu-root/hardware/google/aemu \
    && git -C /opt/aemu-root/hardware/google/aemu sparse-checkout set protos \
    && git clone --filter=blob:none --no-checkout \
       https://github.com/google/android-emulator-container-scripts.git \
       /tmp/emulator-scripts \
    && git -C /tmp/emulator-scripts checkout "$EMULATOR_SCRIPTS_REF" -- gateway \
    && BAZEL_ROOT=/opt/aemu-root pip install --no-cache-dir /tmp/emulator-scripts/gateway \
    && rm -rf /tmp/emulator-scripts /opt/aemu-root

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY flows ./flows

EXPOSE 8000 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
