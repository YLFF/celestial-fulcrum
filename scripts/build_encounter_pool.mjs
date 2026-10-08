import { writeFileSync } from "node:fs";

const url =
  "https://prts.wiki/w/%E6%B2%89%E6%B2%A6%E8%80%85%E7%9A%84%E9%BB%91%E6%B5%81%E6%A0%91%E6%B5%B7/%E4%BA%8B%E4%BB%B6%E4%B8%80%E8%A7%88";

const html = await fetch(url, { headers: { "user-agent": "Mozilla/5.0" } }).then((r) => r.text());

function decodeEntities(value) {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&#039;", "'");
}

const pool = [];
const seen = new Set();
let currentType = null;
const scenePattern = /<div class="scene"([^>]*)>/g;
for (const match of html.matchAll(scenePattern)) {
  const attrs = match[1];
  const etype = attrs.match(/data-etype="([^"]*)"/)?.[1];
  if (etype) currentType = decodeEntities(etype);
  if (currentType !== "不期而遇" || !/data-nav="开始"/.test(attrs)) continue;
  const name = attrs.match(/data-name="([^"]*)"/)?.[1] ?? "";
  if (!name || seen.has(name)) continue;
  seen.add(name);
  const floorsRaw = attrs.match(/data-efloor="([^"]*)"/)?.[1] ?? "";
  const ename = attrs.match(/data-ename="([^"]*)"/)?.[1] ?? "";
  const prtsInfo = attrs.match(/data-prtsinfo="([^"]*)"/)?.[1] ?? "";
  pool.push({
    id: `encounter_${pool.length + 1}`,
    name: decodeEntities(name),
    type: "不期而遇",
    floors: floorsRaw ? floorsRaw.split(",").map((s) => s.trim()).filter(Boolean) : [],
    englishName: decodeEntities(ename),
    prtsInfo: decodeEntities(prtsInfo),
    distribution: null,
    encounterRules: [],
    notes: "",
  });
}

const output = {
  schemaVersion: 1,
  source: {
    name: "PRTS 沉沦者的黑流树海/事件一览",
    url,
    extractedAt: new Date().toISOString(),
    qqDocsCatalog: {
      url: "https://docs.qq.com/sheet/DQkhoWVpEcUF2T3FV?tab=fglwp2",
      tabId: "fglwp2",
      tabName: "树海.事件相关",
      note: "腾讯文档公开首包可确认目录页签；事件明细先以 PRTS 结构化页面抽取，等待人工规则校正。",
    },
  },
  eventPool: pool,
};

writeFileSync("data/blackstream_encounter_pool.json", `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(`wrote ${pool.length} encounter events`);
console.log(pool.map((event) => `${event.name} [${event.floors.join(",") || "?"}]`).join("\n"));
