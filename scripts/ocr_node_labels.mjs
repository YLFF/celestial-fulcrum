import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createWorker } = require('tesseract.js');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { path, mode = '11', rows = {}, labels = [] } = JSON.parse(input);
const worker = await createWorker('chi_sim', 1, {
  langPath: process.cwd(), gzip: false, cacheMethod: 'none', logger: () => {},
});
try {
  await worker.setParameters({ tessedit_pageseg_mode: String(mode) });
  const { data } = await worker.recognize(path, {}, { text: true, tsv: true });
  const lineResults = [];
  const normalized = text => text.replace(/[\s“”‘’"'，。！？、:：;；·]+/g, '');
  const words = String(data.tsv || '').split('\n').map(line => line.split('\t')).filter(row => row[0] === '5');
  const dictionary = new Set(labels.map(normalized));
  for (const [key, row] of Object.entries(rows)) {
    if (!key.endsWith('|gray')) continue;
    const tokens = words.filter(word => Number(word[7]) + Number(word[9]) / 2 >= row.top
      && Number(word[7]) + Number(word[9]) / 2 < row.bottom).sort((a, b) => Number(a[6]) - Number(b[6]));
    if (dictionary.has(normalized(tokens.map(word => word[11]).join('')))
      && tokens.length && tokens.every(word => Number(word[10]) >= 75)) continue;
    await worker.setParameters({ tessedit_pageseg_mode: '7' });
    const result = await worker.recognize(row.path, {}, { text: true, tsv: true });
    lineResults.push({ key, tsv: result.data.tsv });
  }
  process.stdout.write(JSON.stringify({ text: data.text, tsv: data.tsv, lineResults }));
} finally { await worker.terminate(); }
