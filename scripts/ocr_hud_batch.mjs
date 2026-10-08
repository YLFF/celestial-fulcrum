import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createWorker } = require("tesseract.js");

let input = "";
for await (const chunk of process.stdin) input += chunk;
const jobs = JSON.parse(input);
if (!Array.isArray(jobs)) throw new Error("Expected a JSON array of OCR jobs on stdin");

const worker = await createWorker("eng", 1, {
  langPath: process.cwd(),
  gzip: false,
  cacheMethod: "none",
  logger: () => {},
});
try {
  await worker.setParameters({
    tessedit_char_whitelist: "0123456789/",
    tessedit_pageseg_mode: "7",
  });
  const results = {};
  let pageSegMode = "7";
  for (const { name, path, psm = "7" } of jobs) {
    if (psm !== pageSegMode) {
      await worker.setParameters({ tessedit_pageseg_mode: psm });
      pageSegMode = psm;
    }
    const { data } = await worker.recognize(path);
    results[name] = {
      text: String(data.text || "").replace(/\s+/g, ""),
      confidence: typeof data.confidence === "number" ? data.confidence : null,
    };
  }
  process.stdout.write(JSON.stringify(results));
} finally {
  await worker.terminate();
}
