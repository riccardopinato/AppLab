import { expect, test } from "@playwright/test";

const FRONTEND = process.env.APPLAB_FRONTEND_URL || "http://127.0.0.1:5173";
const BACKEND = process.env.APPLAB_BACKEND_URL || "http://127.0.0.1:8000";
const PACKAGE_ID = "dev.applab.selftest";

function nodeBounds(xml, label) {
  const nodes = xml.match(/<node\b[^>]*>/g) || [];
  for (const node of nodes) {
    const hasLabel =
      node.includes(`text="${label}"`) ||
      node.includes(`content-desc="${label}"`);
    if (!hasLabel) continue;

    const match = node.match(
      /bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/,
    );
    if (match) {
      return {
        left: Number(match[1]),
        top: Number(match[2]),
        right: Number(match[3]),
        bottom: Number(match[4]),
      };
    }
  }
  throw new Error(`Unable to locate Android node bounds for: ${label}`);
}

async function hierarchy(request) {
  const response = await request.get(`${BACKEND}/api/ui/hierarchy`);
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return body.xml || "";
}

async function videoDiagnostics(video) {
  return video.evaluate((element) => {
    const stream = element.srcObject instanceof MediaStream ? element.srcObject : null;
    const quality =
      typeof element.getVideoPlaybackQuality === "function"
        ? element.getVideoPlaybackQuality()
        : null;
    return {
      readyState: element.readyState,
      networkState: element.networkState,
      width: element.videoWidth,
      height: element.videoHeight,
      currentTime: element.currentTime,
      paused: element.paused,
      ended: element.ended,
      error: element.error
        ? { code: element.error.code, message: element.error.message }
        : null,
      totalVideoFrames: quality?.totalVideoFrames ?? null,
      droppedVideoFrames: quality?.droppedVideoFrames ?? null,
      tracks: stream
        ? stream.getTracks().map((track) => ({
            kind: track.kind,
            enabled: track.enabled,
            muted: track.muted,
            readyState: track.readyState,
            settings:
              typeof track.getSettings === "function" ? track.getSettings() : {},
          }))
        : [],
    };
  });
}

async function endpointDiagnostics(request, url) {
  try {
    const response = await request.get(url, { timeout: 10_000 });
    const text = await response.text();
    let body = text;
    try {
      body = JSON.parse(text);
    } catch {
      // Preserve raw response text when the endpoint is not JSON.
    }
    return { ok: response.ok(), status: response.status(), body };
  } catch (error) {
    return { ok: false, status: 0, error: String(error) };
  }
}

async function attachFrameRecoveryDiagnostics({
  request,
  video,
  testInfo,
  browserErrors,
  attempt,
  error,
}) {
  const payload = {
    attempt,
    error: String(error),
    video: await videoDiagnostics(video),
    runtime: await endpointDiagnostics(request, `${BACKEND}/api/runtime`),
    gateway: await endpointDiagnostics(
      request,
      "http://127.0.0.1:8080/api/v1/emulator/status",
    ),
    browserErrors: [...browserErrors],
  };
  await testInfo.attach(`webrtc-frame-recovery-attempt-${attempt}.json`, {
    body: Buffer.from(JSON.stringify(payload, null, 2)),
    contentType: "application/json",
  });
}

async function waitForDecodedFrame(video) {
  let last = await videoDiagnostics(video);
  await expect
    .poll(
      async () => {
        last = await videoDiagnostics(video);
        return last.readyState >= 2 && last.width > 0 && last.height > 0;
      },
      {
        timeout: 30_000,
        message: "WebRTC connected but no decoded Android video frame arrived",
      },
    )
    .toBe(true);
  return last;
}

test("streams real Android video and sends real WebRTC input", async ({
  page,
  request,
}, testInfo) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.addInitScript(() => {
    window.__applabRtcInputProbe = {
      events: [],
      channels: {},
    };

    const originalCreateDataChannel = RTCPeerConnection.prototype.createDataChannel;
    RTCPeerConnection.prototype.createDataChannel = function (label, options) {
      const channel = originalCreateDataChannel.call(this, label, options);
      window.__applabRtcInputProbe.channels[label] = channel;
      window.__applabRtcInputProbe.events.push({
        type: "create",
        label,
        readyState: channel.readyState,
        at: Date.now(),
      });
      channel.addEventListener("open", () => {
        window.__applabRtcInputProbe.events.push({
          type: "open",
          label: channel.label,
          readyState: channel.readyState,
          at: Date.now(),
        });
      });
      channel.addEventListener("close", () => {
        window.__applabRtcInputProbe.events.push({
          type: "close",
          label: channel.label,
          readyState: channel.readyState,
          at: Date.now(),
        });
      });
      channel.addEventListener("error", () => {
        window.__applabRtcInputProbe.events.push({
          type: "error",
          label: channel.label,
          readyState: channel.readyState,
          at: Date.now(),
        });
      });
      return channel;
    };

    const originalSend = RTCDataChannel.prototype.send;
    RTCDataChannel.prototype.send = function (data) {
      const byteLength =
        typeof data?.byteLength === "number"
          ? data.byteLength
          : typeof data?.size === "number"
            ? data.size
            : typeof data?.length === "number"
              ? data.length
              : null;
      window.__applabRtcInputProbe.events.push({
        type: "send",
        label: this.label,
        readyState: this.readyState,
        byteLength,
        bufferedAmount: this.bufferedAmount,
        at: Date.now(),
      });
      return originalSend.call(this, data);
    };
  });

  await page.goto(FRONTEND, { waitUntil: "domcontentloaded" });

  let liveView;
  let video;
  let first;

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    liveView = page.getByTestId("device-live-view");
    await expect(liveView).toHaveAttribute("data-webrtc-state", "connected", {
      timeout: 60_000,
    });

    video = liveView.locator("video");
    await expect(video).toBeVisible();

    try {
      first = await waitForDecodedFrame(video);
      break;
    } catch (error) {
      await attachFrameRecoveryDiagnostics({
        request,
        video,
        testInfo,
        browserErrors,
        attempt,
        error,
      });
      if (attempt === 2) throw error;

      // A connected signaling channel with no decoded frame is an observed
      // transient infrastructure signature. Recreate the browser peer once,
      // then rerun the exact same frame assertions; never convert it to PASS.
      await page.reload({ waitUntil: "domcontentloaded" });
    }
  }

  if (!liveView || !video || !first) {
    throw new Error("WebRTC frame recovery exhausted without a decoded frame");
  }

  expect(first.readyState).toBeGreaterThanOrEqual(2);
  expect(first.width).toBeGreaterThan(0);
  expect(first.height).toBeGreaterThan(0);

  await expect
    .poll(async () => video.evaluate((element) => {
      const canvas = document.createElement("canvas");
      canvas.width = 64;
      canvas.height = 64;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return false;

      context.drawImage(element, 0, 0, canvas.width, canvas.height);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let min = 255;
      let max = 0;
      let bright = 0;
      const samples = pixels.length / 4;

      for (let i = 0; i < pixels.length; i += 4) {
        const luma =
          pixels[i] * 0.2126 +
          pixels[i + 1] * 0.7152 +
          pixels[i + 2] * 0.0722;
        min = Math.min(min, luma);
        max = Math.max(max, luma);
        if (luma > 80) bright += 1;
      }

      return max - min > 60 && bright / samples > 0.002;
    }), {
      timeout: 20_000,
      message: "WebRTC connected but no non-black Android frame was decoded",
    })
    .toBe(true);

  const frameStats = await video.evaluate((element) => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas 2D context unavailable");

    context.drawImage(element, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let min = 255;
    let max = 0;
    let sum = 0;
    let bright = 0;
    const samples = pixels.length / 4;

    for (let i = 0; i < pixels.length; i += 4) {
      const luma =
        pixels[i] * 0.2126 +
        pixels[i + 1] * 0.7152 +
        pixels[i + 2] * 0.0722;
      min = Math.min(min, luma);
      max = Math.max(max, luma);
      sum += luma;
      if (luma > 80) bright += 1;
    }

    return {
      readyState: element.readyState,
      width: element.videoWidth,
      height: element.videoHeight,
      currentTime: element.currentTime,
      lumaRange: max - min,
      meanLuma: sum / samples,
      brightRatio: bright / samples,
    };
  });

  expect(frameStats.readyState).toBeGreaterThanOrEqual(2);
  expect(frameStats.width).toBeGreaterThan(0);
  expect(frameStats.height).toBeGreaterThan(0);
  expect(frameStats.lumaRange).toBeGreaterThan(60);
  expect(frameStats.brightRatio).toBeGreaterThan(0.002);

  await testInfo.attach("webrtc-frame-stats.json", {
    body: Buffer.from(JSON.stringify({ first, frame: frameStats }, null, 2)),
    contentType: "application/json",
  });

  const beforeXml = await hierarchy(request);
  expect(beforeXml).toContain("RUN INTERACTION TEST");

  const bounds = nodeBounds(beforeXml, "RUN INTERACTION TEST");
  const handler = video.locator("..");
  await handler.scrollIntoViewIfNeeded();
  await expect(handler).toBeVisible();
  const handlerBox = await handler.boundingBox();
  if (!handlerBox) throw new Error("WebRTC input handler has no browser bounding box");

  // Use the same gateway display metadata consumed by upstream
  // android-emulator-webrtc. Missing dimensions are a contract failure because
  // a guessed fallback can silently misroute pointer input.
  const gatewayStatus = await endpointDiagnostics(
    request,
    "http://127.0.0.1:8080/api/v1/emulator/status",
  );
  expect(gatewayStatus.ok).toBeTruthy();
  const hardwareConfig =
    gatewayStatus.body?.platformConfig || gatewayStatus.body?.hardwareConfig || {};
  const inputWidth = Number(hardwareConfig["hw.lcd.width"]);
  const inputHeight = Number(hardwareConfig["hw.lcd.height"]);
  expect(Number.isFinite(inputWidth) && inputWidth > 0).toBeTruthy();
  expect(Number.isFinite(inputHeight) && inputHeight > 0).toBeTruthy();

  const nativeX = (bounds.left + bounds.right) / 2;
  const nativeY = (bounds.top + bounds.bottom) / 2;
  const deviceRatio = inputWidth / inputHeight;
  const containerRatio = handlerBox.width / handlerBox.height;

  let renderedWidth = handlerBox.width;
  let renderedHeight = handlerBox.height;
  let offsetX = 0;
  let offsetY = 0;

  if (containerRatio > deviceRatio) {
    renderedWidth = handlerBox.height * deviceRatio;
    offsetX = (handlerBox.width - renderedWidth) / 2;
  } else {
    renderedHeight = handlerBox.width / deviceRatio;
    offsetY = (handlerBox.height - renderedHeight) / 2;
  }

  const browserX =
    handlerBox.x + offsetX + (nativeX / inputWidth) * renderedWidth;
  const browserY =
    handlerBox.y + offsetY + (nativeY / inputHeight) * renderedHeight;

  const inputChannelState = await page.evaluate(() => {
    const probe = window.__applabRtcInputProbe;
    const channel = probe?.channels?.mouse;
    return {
      readyState: channel?.readyState || "missing",
      bufferedAmount: channel?.bufferedAmount ?? null,
      events: probe?.events || [],
    };
  });
  await testInfo.attach("webrtc-input-channel-before-click.json", {
    body: Buffer.from(JSON.stringify(inputChannelState, null, 2)),
    contentType: "application/json",
  });

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const beforeAttempt = await endpointDiagnostics(
      request,
      `${BACKEND}/api/ui/hierarchy`,
    );
    const alreadyApplied =
      beforeAttempt.ok &&
      typeof beforeAttempt.body === "object" &&
      String(beforeAttempt.body?.xml || "").includes("INTERACTION_OK");
    if (alreadyApplied) break;

    await page.mouse.move(browserX, browserY);
    await page.mouse.down({ button: "left" });
    await page.waitForTimeout(80);
    await page.mouse.up({ button: "left" });

    try {
      await expect
        .poll(async () => {
          const snapshot = await endpointDiagnostics(
            request,
            `${BACKEND}/api/ui/hierarchy`,
          );
          return (
            snapshot.ok &&
            typeof snapshot.body === "object" &&
            String(snapshot.body?.xml || "").includes("INTERACTION_OK")
          );
        }, {
          timeout: 20_000,
          message: "Android UI did not react to the WebRTC pointer input",
        })
        .toBe(true);
      break;
    } catch (error) {
      const payload = {
        attempt,
        error: String(error),
        native: { x: nativeX, y: nativeY, bounds },
        browser: { x: browserX, y: browserY, handlerBox },
        hierarchy: await endpointDiagnostics(
          request,
          `${BACKEND}/api/ui/hierarchy`,
        ),
        runtime: await endpointDiagnostics(request, `${BACKEND}/api/runtime`),
        gateway: await endpointDiagnostics(
          request,
          "http://127.0.0.1:8080/api/v1/emulator/status",
        ),
        browserErrors: [...browserErrors],
        inputChannel: await page.evaluate(() => {
          const probe = window.__applabRtcInputProbe;
          const channel = probe?.channels?.mouse;
          return {
            readyState: channel?.readyState || "missing",
            bufferedAmount: channel?.bufferedAmount ?? null,
            events: probe?.events || [],
          };
        }),
      };
      await testInfo.attach(`webrtc-pointer-recovery-attempt-${attempt}.json`, {
        body: Buffer.from(JSON.stringify(payload, null, 2)),
        contentType: "application/json",
      });

      if (attempt === 2) throw error;
    }
  }

  const finalHierarchy = await endpointDiagnostics(
    request,
    `${BACKEND}/api/ui/hierarchy`,
  );
  expect(finalHierarchy.ok).toBeTruthy();
  expect(
    typeof finalHierarchy.body === "object" &&
      String(finalHierarchy.body?.xml || "").includes("INTERACTION_OK"),
  ).toBe(true);

  const inputAfter = await page.evaluate(() => {
    const probe = window.__applabRtcInputProbe;
    const events = probe?.events || [];
    return {
      events,
      mouseSendCount: events.filter(
        (event) => event.type === "send" && event.label === "mouse",
      ).length,
    };
  });
  await testInfo.attach("webrtc-input-channel-after-click.json", {
    body: Buffer.from(JSON.stringify(inputAfter, null, 2)),
    contentType: "application/json",
  });
  expect(inputAfter.mouseSendCount).toBeGreaterThanOrEqual(2);

  const browserShot = testInfo.outputPath("browser-webrtc-connected.png");
  await page.screenshot({ path: browserShot, fullPage: true });
  await testInfo.attach("browser-webrtc-connected.png", {
    path: browserShot,
    contentType: "image/png",
  });

  await page.getByTestId("hardware-home").click();

  await expect
    .poll(async () => {
      const response = await request.get(
        `${BACKEND}/api/app/status?package_id=${PACKAGE_ID}`,
      );
      if (!response.ok()) return true;
      const body = await response.json();
      return body.foreground === false;
    }, {
      timeout: 15_000,
      message: "WebRTC hardware Home key did not leave the self-test app",
    })
    .toBe(true);

  await testInfo.attach("browser-console-errors.json", {
    body: Buffer.from(JSON.stringify(browserErrors, null, 2)),
    contentType: "application/json",
  });
});
