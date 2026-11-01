#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = path.join(ROOT, "config.json");
const SITE_DIR = path.join(ROOT, "site");
const TARGET_WIDTH = 1146;
const TARGET_HEIGHT = 797;

function usage() {
  console.error(
    "Usage: node Tools/cover-renderer/render-cover.mjs " +
      "--version <version> --detail <commit> --output <cover.png>",
  );
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument: ${key}`);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`Missing value for ${key}`);
    }
    args[key.slice(2)] = value;
    i += 1;
  }
  return args;
}

function cleanText(value, name, maxLength) {
  const cleaned = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
  if (!cleaned) throw new Error(`${name} must not be empty`);
  return cleaned;
}

async function freePort() {
  const server = net.createServer();
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForServer(url, server, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Static server exited with code ${server.exitCode}`);
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) return;
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  ].filter(Boolean);
  const executable = candidates.find((candidate) => existsSync(candidate));
  if (!executable) {
    throw new Error(
      "Google Chrome not found. Set CHROME_BIN to a Chrome/Chromium executable.",
    );
  }
  return executable;
}

async function waitForCanvasPixels(page, canvasId, timeoutMs = 15_000) {
  await page.waitForFunction(
    (id) => {
      const canvas = document.getElementById(id);
      if (!canvas) return false;
      const pixels = canvas.getContext("2d").getImageData(
        0,
        0,
        canvas.width,
        canvas.height,
      ).data;
      for (let i = 3; i < pixels.length; i += 64) {
        if (pixels[i] !== 0) return true;
      }
      return false;
    },
    canvasId,
    { timeout: timeoutMs },
  );
}

async function selectIllustration(page, editorIndex, title) {
  const editor = page.locator(".rahoo-illust-editor").nth(editorIndex);
  await editor.locator(".el-tabs__item", { hasText: "明日方舟" }).click();

  const select = editor.locator(".el-select:visible");
  await select.click();
  const input = select.locator("input");
  await input.fill(title);
  await page.waitForTimeout(250);
  await input.press("Enter");
  await page.waitForFunction(
    ({ index, expected }) => {
      const editors = document.querySelectorAll(".rahoo-illust-editor");
      const select = editors[index]?.querySelector(".el-select");
      return select && select.textContent.includes(expected);
    },
    { index: editorIndex, expected: title },
  );
  await page.waitForTimeout(400);
}

async function applyImagePosition(page, editorIndex, position) {
  const canvas = page.locator("#imageControlPanel").nth(editorIndex);
  await canvas.evaluate((element, delta) => {
    const startX = 100;
    const startY = 100;
    element.dispatchEvent(
      new MouseEvent("mousedown", {
        clientX: startX,
        clientY: startY,
        bubbles: true,
      }),
    );
    element.dispatchEvent(
      new MouseEvent("mousemove", {
        clientX: startX + delta.x,
        clientY: startY + delta.y,
        bubbles: true,
      }),
    );
    element.dispatchEvent(
      new MouseEvent("mouseup", {
        clientX: startX + delta.x,
        clientY: startY + delta.y,
        bubbles: true,
      }),
    );
  }, position);
}

async function validatePng(file) {
  const data = await readFile(file);
  if (
    data.length < 24 ||
    data[0] !== 0x89 ||
    data.subarray(1, 4).toString("ascii") !== "PNG"
  ) {
    throw new Error(`Renderer did not produce a valid PNG: ${file}`);
  }
  const width = data.readUInt32BE(16);
  const height = data.readUInt32BE(20);
  if (width !== TARGET_WIDTH || height !== TARGET_HEIGHT) {
    throw new Error(`Unexpected cover size ${width}x${height}`);
  }
  if (data.length < 50_000) {
    throw new Error(`Cover output is unexpectedly small (${data.length} bytes)`);
  }
  return { width, height, bytes: data.length };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.version || !args.output) {
    usage();
    throw new Error("--version and --output are required");
  }

  const config = JSON.parse(await readFile(CONFIG_PATH, "utf8"));
  const version = cleanText(args.version, "version", 24);
  const detail = cleanText(args.detail ?? "unknown", "detail", 24);
  const output = path.resolve(args.output);
  await mkdir(path.dirname(output), { recursive: true });

  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  let serverLog = "";
  const server = spawn(
    process.env.PYTHON || "python3",
    [path.join(SITE_DIR, "serve.py"), "--no-browser", "--port", String(port)],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  server.stdout.on("data", (chunk) => {
    serverLog += chunk;
  });
  server.stderr.on("data", (chunk) => {
    serverLog += chunk;
  });

  let browser;
  let dialogError = null;
  try {
    await waitForServer(`${baseUrl}/`, server);
    browser = await chromium.launch({
      executablePath: findChrome(),
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 1,
      acceptDownloads: true,
    });
    page.on("dialog", async (dialog) => {
      dialogError = new Error(`Page dialog: ${dialog.message()}`);
      await dialog.dismiss();
    });

    const illustrations = config.illustrations;
    await page.route(/^https:\/\//, async (route) => {
      const requestUrl = route.request().url();
      const illustration = illustrations.find((item) =>
        requestUrl.includes(item.remoteMatch),
      );
      if (!illustration) {
        await route.abort();
        return;
      }
      await route.fulfill({
        path: path.join(ROOT, illustration.image),
        contentType: "image/png",
        headers: { "access-control-allow-origin": "*" },
      });
    });

    await page.goto(`${baseUrl}/cover/${config.template}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await page.locator("#titleText").waitFor({ timeout: 30_000 });

    for (const [id, value] of Object.entries(config.fields)) {
      await page.locator(`#${id}`).fill(value);
    }
    await page.locator("#titleText").fill(version);
    await page.locator("#gilroyWord3").fill(detail);

    for (let i = 0; i < illustrations.length; i += 1) {
      const illustration = illustrations[i];
      await selectIllustration(page, i, illustration.title);
      const editor = page.locator(".rahoo-illust-editor").nth(i);
      await editor.locator("input[type=number]").fill(String(illustration.scale));
      await applyImagePosition(page, i, illustration.position);
    }

    await waitForCanvasPixels(page, "illustA");
    await waitForCanvasPixels(page, "illustB");
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(800);

    if (dialogError) throw dialogError;
    const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
    await page.locator(".r-cover-save").click();
    const download = await downloadPromise;
    await download.saveAs(output);
    const result = await validatePng(output);
    console.log(
      `[cover] ${version} / ${detail} -> ${output} ` +
        `(${result.width}x${result.height}, ${result.bytes} bytes)`,
    );
  } catch (error) {
    if (serverLog.trim()) console.error(serverLog.trim());
    throw error;
  } finally {
    if (browser) await browser.close().catch(() => {});
    server.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(`[cover] ${error.stack || error.message || error}`);
  process.exit(1);
});
