ARG EMULATOR_BASE_IMAGE=us-docker.pkg.dev/android-emulator-268719/images/30-google-x64-no-metrics:7148297
FROM ${EMULATOR_BASE_IMAGE}

ARG EMULATOR_PACKAGE_URL=https://dl.google.com/android/repository/emulator-linux_x64-15917651.zip
ARG EMULATOR_PACKAGE_SHA1=1b1f78891abf8ec268264356e1365c25519e8379

USER root

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl unzip libxkbfile1; \
    rm -rf /var/lib/apt/lists/*; \
    tmp_zip="$(mktemp)"; \
    tmp_dir="$(mktemp -d)"; \
    curl -fsSL "${EMULATOR_PACKAGE_URL}" -o "${tmp_zip}"; \
    printf '%s  %s\n' "${EMULATOR_PACKAGE_SHA1}" "${tmp_zip}" | sha1sum -c -; \
    unzip -q "${tmp_zip}" -d "${tmp_dir}"; \
    if [ -f /android/sdk/emulator/package.xml ]; then \
      cp /android/sdk/emulator/package.xml "${tmp_dir}/emulator/package.xml"; \
      sed -i '/<revision>/,/<\/revision>/c\    <revision>\n      <major>37</major>\n      <minor>1</minor>\n      <micro>11</micro>\n    </revision>' "${tmp_dir}/emulator/package.xml"; \
    fi; \
    rm -rf /android/sdk/emulator; \
    mv "${tmp_dir}/emulator" /android/sdk/emulator; \
    rm -rf "${tmp_zip}" "${tmp_dir}"; \
    /android/sdk/emulator/emulator -version | tee /tmp/applab-emulator-version.txt; \
    grep -Fq "Android emulator version 37.1.11" /tmp/applab-emulator-version.txt
