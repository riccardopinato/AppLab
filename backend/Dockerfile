FROM python:3.12-slim

ARG EMULATOR_SCRIPTS_REF=0654f694b46794fae4b178f1e1a17cb60c5d2d34
ARG AEMU_REF=b556b00ac5fffde13c5cbad1b659c528832f9da6
ARG MAESTRO_VERSION=2.10.0
ARG MAESTRO_SHA256=29b675e10cc12080e445e9bfb2e2b4e4dfb9c0f2e30d5884120d258b5e1cd991

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

RUN mkdir -p /root/.maestro/tmp \
    && curl -fsSL --retry 3 \
       "https://github.com/mobile-dev-inc/Maestro/releases/download/cli-$MAESTRO_VERSION/maestro.zip" \
       -o /root/.maestro/tmp/maestro.zip \
    && echo "$MAESTRO_SHA256  /root/.maestro/tmp/maestro.zip" | sha256sum -c - \
    && unzip -qt /root/.maestro/tmp/maestro.zip | grep -F "No errors detected in compressed data" \
    && unzip -qo /root/.maestro/tmp/maestro.zip -d /root/.maestro/tmp \
    && cp -rf /root/.maestro/tmp/maestro/* /root/.maestro \
    && rm -rf /root/.maestro/tmp \
    && MAESTRO_CLI_NO_ANALYTICS=1 maestro --version | grep -F "$MAESTRO_VERSION"

# Install Google's current Python WebRTC signaling gateway. The gateway build
# generates its protobuf stubs from the Android Emulator AEMU proto sources.
RUN mkdir -p /opt/aemu-root/hardware/google \
    && git init /opt/aemu-root/hardware/google/aemu \
    && git -C /opt/aemu-root/hardware/google/aemu remote add origin \
       https://android.googlesource.com/platform/hardware/google/aemu \
    && git -C /opt/aemu-root/hardware/google/aemu sparse-checkout init --cone \
    && git -C /opt/aemu-root/hardware/google/aemu sparse-checkout set protos \
    && git -C /opt/aemu-root/hardware/google/aemu fetch --depth 1 origin "$AEMU_REF" \
    && git -C /opt/aemu-root/hardware/google/aemu checkout --detach FETCH_HEAD \
    && git clone --filter=blob:none --no-checkout \
       https://github.com/google/android-emulator-container-scripts.git \
       /tmp/emulator-scripts \
    && git -C /tmp/emulator-scripts checkout "$EMULATOR_SCRIPTS_REF" -- gateway \
    && BAZEL_ROOT=/opt/aemu-root pip install --no-cache-dir /tmp/emulator-scripts/gateway \
    && python - <<'PY'
import pathlib
import shutil
import site

source = pathlib.Path(
    "/tmp/emulator-scripts/gateway/src/videobridge_gateway/proto"
)
if not source.is_dir():
    raise SystemExit(f"Generated gateway proto directory missing: {source}")

target = pathlib.Path(site.getsitepackages()[0]) / "videobridge_gateway" / "proto"
shutil.copytree(source, target, dirs_exist_ok=True)

required = (
    "emulator_controller_pb2.py",
    "emulator_controller_pb2_grpc.py",
    "rtc_service_v2_pb2.py",
    "rtc_service_v2_pb2_grpc.py",
    "ice_config_pb2.py",
)
missing = [name for name in required if not (target / name).is_file()]
if missing:
    raise SystemExit(f"Missing generated gateway proto modules: {missing}")
PY
RUN python -c "import videobridge_gateway.gateway_server" \
    && videobridge-gateway --help >/dev/null \
    && rm -rf /tmp/emulator-scripts /opt/aemu-root

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY flows ./flows

EXPOSE 8000 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${APPLAB_BIND_HOST:-0.0.0.0} --port 8000"]
