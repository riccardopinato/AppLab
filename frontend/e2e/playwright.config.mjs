import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: /live-webrtc\.spec\.mjs/,
  timeout: 120_000,
  expect: {
    timeout: 30_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  outputDir: "test-results",
  use: {
    browserName: "chromium",
    headless: true,
    hasTouch: true,
    viewport: { width: 1440, height: 1100 },
    launchOptions: {
      args: [
        "--autoplay-policy=no-user-gesture-required",
        "--disable-dev-shm-usage",
      ],
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
