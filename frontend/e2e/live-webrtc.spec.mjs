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

test("streams real Android video and sends real WebRTC input", async ({
  page,
  request,
}, testInfo) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.goto(FRONTEND, { waitUntil: "domcontentloaded" });

  const liveView = page.getByTestId("device-live-view");
  await expect(liveView).toHaveAttribute("data-webrtc-state", "connected", {
    timeout: 60_000,
  });

  const video = liveView.locator("video");
  await expect(video).toBeVisible();

  await expect
    .poll(async () => {
      return video.evaluate(
        (element) =>
          element.readyState >= 2 &&
          element.videoWidth > 0 &&
          element.videoHeight > 0,
      );
    }, {
      timeout: 30_000,
      message: "WebRTC connected but no decoded Android video frame arrived",
    })
    .toBe(true);

  const first = await video.evaluate((element) => ({
    readyState: element.readyState,
    width: element.videoWidth,
    height: element.videoHeight,
    currentTime: element.currentTime,
  }));

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
  const box = await video.boundingBox();
  if (!box) throw new Error("WebRTC video has no browser bounding box");

  // Click the WebRTC handler at the Android node's normalized position.
  // The upstream event handler performs its own letterbox/device scaling, so
  // feeding already letterbox-adjusted browser coordinates would scale twice.
  const nativeX = (bounds.left + bounds.right) / 2;
  const nativeY = (bounds.top + bounds.bottom) / 2;
  const browserX = box.x + (nativeX / first.width) * box.width;
  const browserY = box.y + (nativeY / first.height) * box.height;

  await page.mouse.move(browserX, browserY);
  await page.mouse.down({ button: "left" });
  await page.waitForTimeout(80);
  await page.mouse.up({ button: "left" });

  await expect
    .poll(async () => (await hierarchy(request)).includes("INTERACTION_OK"), {
      timeout: 20_000,
      message: "Android UI did not react to the WebRTC pointer input",
    })
    .toBe(true);

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
