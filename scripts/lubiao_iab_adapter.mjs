import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const LUBIAO_URL = "https://www.lubiao.wiki/tools/blackstream-route";
const BROWSER_CLIENT = "C:/Users/Lean/.codex/plugins/cache/openai-bundled/browser/26.803.81509/scripts/browser-client.mjs";

async function clickByText(page, text, timeout = 30000) {
  const locator = page.getByText(text, { exact: false }).first();
  await locator.waitFor({ state: "visible", timeout });
  await locator.click();
}

async function waitUntil(page, predicateSource, timeout = 120000, interval = 500) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const ok = await page.evaluate(predicateSource);
    if (ok) return;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, interval));
  }
  throw new Error(`Timed out after ${timeout}ms waiting for page condition`);
}

async function waitForMapNodes(page, timeout = 120000) {
  await waitUntil(
    page,
    () => document.querySelectorAll("[class*='has-prediction'], [class*='has-start']").length > 0,
    timeout,
  );
}

async function extractRecognitionResult(page) {
  return await page.evaluate(() => {
    function cellKeyFor(element) {
      const direct = element.getAttribute("data-cell-key") || element.getAttribute("cellkey");
      if (direct) return direct;
      const cell = element.closest("[data-cell-key], [cellkey], [class*='cell']");
      return cell?.getAttribute("data-cell-key") || cell?.getAttribute("cellkey") || "";
    }

    const nodeElements = Array.from(document.querySelectorAll("[class*='has-node'], [class*='has-start'], [class*='has-prediction']"));
    const seen = new Set();
    const byCell = new Map();
    for (const element of nodeElements) {
      const cellKey = cellKeyFor(element);
      if (!cellKey) continue;
      const node = {
        cellKey,
        text: element.textContent?.trim() || "",
        nodeClass: element.className?.toString() || "",
        cellClass: element.closest("[class*='cell']")?.className?.toString() || "",
      };
      const dedupeKey = `${node.cellKey}|${node.nodeClass}|${node.text}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);
      const existing = byCell.get(cellKey);
      const isInnerNode = node.nodeClass.includes("blackstream-map-node");
      const existingIsInnerNode = existing?.nodeClass?.includes("blackstream-map-node");
      if (!existing || (isInnerNode && !existingIsInnerNode)) {
        byCell.set(cellKey, node);
      }
    }
    const nodes = Array.from(byCell.values());

    return {
      ok: true,
      recognizer: "lubiao-iab-local",
      url: location.href,
      title: document.title,
      nodeCount: nodes.length,
      predictionCount: nodes.filter((node) => node.nodeClass.includes("has-prediction")).length,
      nodes,
    };
  });
}

export async function recognizeWithLubiaoIab({ screenshotPath, outPath, screenshotOutPath } = {}) {
  if (!screenshotPath) throw new Error("screenshotPath is required");

  const { setupBrowserRuntime } = await import(pathToFileURL(BROWSER_CLIENT).href);
  const agent = await setupBrowserRuntime();
  const browser = await agent.browsers.get("iab");
  const tab = await browser.tabs.new();
  const page = tab.playwright;

  await tab.goto(LUBIAO_URL);
  await page.waitForLoadState("domcontentloaded");

  const chooserPromise = page.waitForEvent("filechooser");
  const uploadZone = page.locator(".screenshot-entry-zone").first();
  await uploadZone.waitFor({ state: "visible", timeout: 30000 });
  await uploadZone.click();
  const chooser = await chooserPromise;
  await chooser.setFiles([resolve(screenshotPath)]);

  await clickByText(page, "开始识别");
  await clickByText(page, "本地识别");
  await clickByText(page, "在此设备上识别");
  await waitUntil(
    page,
    () => document.body.innerText.includes("识别完成，可在地图上预览"),
    180000,
  );
  const previewButton = page.locator(".primary-action").first();
  await previewButton.waitFor({ state: "visible", timeout: 30000 });
  await previewButton.click();
  await waitForMapNodes(page);

  const result = await extractRecognitionResult(page);
  if (screenshotOutPath) {
    await mkdir(dirname(resolve(screenshotOutPath)), { recursive: true });
    await tab.screenshot({ path: resolve(screenshotOutPath), fullPage: true });
    result.previewPath = screenshotOutPath;
  }
  if (outPath) {
    await mkdir(dirname(resolve(outPath)), { recursive: true });
    await writeFile(outPath, JSON.stringify(result, null, 2), "utf8");
  }
  return result;
}
