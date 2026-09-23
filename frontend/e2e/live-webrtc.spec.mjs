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
      return video.evaluate((element) => ({
        readyState: element.readyState,
        width: element.videoWidth,
        height: element.videoHeight,
        currentTime: element.currentTime,
      }));
    }, {
      timeout: 30_000,
      message: "WebRTC connected but no decoded Android video frame arrived",
    })
    .toMatchObject({
      readyState: 4,
    });

  const first = await video.evaluate((element) => ({
    readyState: element.readyState,
    width: element.videoWidth,
    height: element.videoHeight,
    currentTime: element.currentTime,
  }));

  expect(first.readyState).toBeGreaterThanOrEqual(2);
  expect(first.width).toBeGreaterThan(0);
  expect(first.height).toBeGreaterThan(0);

  await page.waitForTimeout(1_500);

  const frame = await video.evaluate((element) => {
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

  expect(frame.readyState).toBeGreaterThanOrEqual(2);
  expect(frame.currentTime).toBeGreaterThan(first.currentTime);
  expect(frame.lumaRange).toBeGreaterThan(60);
  expect(frame.brightRatio).toBeGreaterThan(0.002);

  await testInfo.attach("webrtc-frame-stats.json", {
    body: Buffer.from(JSON.stringify(frame, null, 2)),
    contentType: "application/json",
  });

  const beforeXml = await hierarchy(request);
  expect(beforeXml).toContain("RUN INTERACTION TEST");

  const bounds = nodeBounds(beforeXml, "RUN INTERACTION TEST");
  const box = await video.boundingBox();
  if (!box) throw new Error("WebRTC video has no browser bounding box");

  const deviceWidth = first.width;
  const deviceHeight = first.height;
  const deviceRatio = deviceWidth / deviceHeight;
  const containerRatio = box.width / box.height;

  let renderedWidth = box.width;
  let renderedHeight = box.height;
  let offsetX = 0;
  let offsetY = 0;

  if (containerRatio > deviceRatio) {
    renderedWidth = box.height * deviceRatio;
    offsetX = (box.width - renderedWidth) / 2;
  } else {
    renderedHeight = box.width / deviceRatio;
    offsetY = (box.height - renderedHeight) / 2;
  }

  const nativeX = (bounds.left + bounds.right) / 2;
  const nativeY = (bounds.top + bounds.bottom) / 2;
  const browserX =
    box.x + offsetX + (nativeX / deviceWidth) * renderedWidth;
  const browserY =
    box.y + offsetY + (nativeY / deviceHeight) * renderedHeight;

  await page.touchscreen.tap(browserX, browserY);

  await expect
    .poll(async () => (await hierarchy(request)).includes("INTERACTION_OK"), {
      timeout: 20_000,
      message: "Android UI did not react to the WebRTC touch input",
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
