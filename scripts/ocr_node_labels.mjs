import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createWorker } = require('tesseract.js');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { path } = JSON.parse(input);
const worker = await createWorker('chi_sim', 1, {
  langPath: process.cwd(), gzip: false, cacheMethod: 'none', logger: () => {},
});
try {
  await worker.setParameters({ tessedit_pageseg_mode: '11' });
  const { data } = await worker.recognize(path, {}, { text: true, tsv: true });
  process.stdout.write(JSON.stringify({ text: data.text, tsv: data.tsv }));
} finally { await worker.terminate(); }
