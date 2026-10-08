import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createWorker } = require(
  "C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/tesseract.js/src/index.js",
);

const imagePath = process.argv[2];
if (!imagePath) {
  console.error("usage: node scripts/ocr_resources_tesseract.mjs <image>");
  process.exit(2);
}
const pageSegMode = process.argv[3] || "7";

const worker = await createWorker("eng", 1, {
  logger: () => {},
});

await worker.setParameters({
  tessedit_char_whitelist: "0123456789/",
  tessedit_pageseg_mode: pageSegMode,
});

try {
  const { data } = await worker.recognize(imagePath);
  const text = String(data.text || "").replace(/\s+/g, "");
  const confidence = typeof data.confidence === "number" ? data.confidence : null;
  console.log(JSON.stringify({ text, confidence }, null, 2));
} finally {
  await worker.terminate();
}
