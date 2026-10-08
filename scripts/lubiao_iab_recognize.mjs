import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const screenshotPath = process.argv[2];
const outPath = process.argv[3] || "work/iab_lubiao_local_result.json";

if (!screenshotPath) {
  console.error("usage: node scripts/lubiao_iab_recognize.mjs <screenshot> [out.json]");
  process.exit(2);
}

const browserClientUrl = pathToFileURL(
  "C:/Users/Lean/.codex/plugins/cache/openai-bundled/browser/26.803.81509/scripts/browser-client.mjs",
);
const { setupBrowserRuntime } = await import(browserClientUrl.href);

const agent = await setupBrowserRuntime();
const browser = await agent.browsers.get("iab");
const tab = await browser.tabs.new("https://www.lubiao.wiki/tools/blackstream-route");
const page = tab.playwright;

async function clickByText(text, timeout = 30000) {
  const locator = page.getByText(text, { exact: false }).first();
  await locator.waitFor({ timeout });
  await locator.click();
}

async function waitForMapNodes(timeout = 120000) {
  await page.waitForFunction(
    () => {
      const nodes = document.querySelectorAll("[class*='has-prediction'], [class*='has-start']");
      return nodes.length > 0;
    },
    undefined,
    { timeout },
  );
}

await page.waitForLoadState("domcontentloaded");

const chooserPromise = page.waitForEvent("filechooser");
await clickByText("上传");
const chooser = await chooserPromise;
await chooser.setFiles([resolve(screenshotPath)]);

await clickByText("开始识别");
await clickByText("本地识别");
await clickByText("在此设备上识别");
await clickByText("在地图上预览识别结果", 180000);
await waitForMapNodes();

const result = await page.evaluate(() => {
  const nodeElements = Array.from(document.querySelectorAll("[class*='has-node'], [class*='has-start'], [class*='has-prediction']"));
  const nodes = nodeElements
    .map((element) => {
      const cell = element.closest("[data-cell-key], [class*='cell']");
      const cellKey =
        element.getAttribute("data-cell-key") ||
        cell?.getAttribute("data-cell-key") ||
        element.getAttribute("cellkey") ||
        cell?.getAttribute("cellkey") ||
        "";
      return {
        cellKey,
        text: element.textContent?.trim() || "",
        nodeClass: element.className?.toString() || "",
        cellClass: cell?.className?.toString() || "",
      };
    })
    .filter((node, index, array) => {
      const key = `${node.cellKey}|${node.nodeClass}|${node.text}`;
      return node.cellKey && array.findIndex((candidate) => `${candidate.cellKey}|${candidate.nodeClass}|${candidate.text}` === key) === index;
    });

  return {
    ok: true,
    url: location.href,
    title: document.title,
    nodeCount: nodes.length,
    predictionCount: nodes.filter((node) => node.nodeClass.includes("has-prediction")).length,
    nodes,
  };
});

await mkdir(resolve(outPath, ".."), { recursive: true });
await writeFile(outPath, JSON.stringify(result, null, 2), "utf8");
console.log(outPath);
