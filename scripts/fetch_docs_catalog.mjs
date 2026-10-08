const pageUrl = "https://docs.qq.com/sheet/DQkhoWVpEcUF2T3FV?tab=fglwp2";
const html = await fetch(pageUrl).then((r) => r.text());

const match = html.match(/href="([^"]*dop-api\/opendoc[^"]+)"/);
if (!match) {
  throw new Error("opendoc preload URL not found");
}

const opendocUrl = new URL(match[1].replaceAll("&amp;", "&"), pageUrl);
console.error(String(opendocUrl));
const response = await fetch(opendocUrl, {
  headers: {
    "referer": pageUrl,
    "user-agent": "Mozilla/5.0",
  },
});
console.error("status", response.status, response.headers.get("content-type"));
const body = await response.text();
console.error("opendoc length", body.length);
const jsonText = body.replace(/^clientVarsCallback\(/, "").replace(/\);?$/, "");
const data = JSON.parse(jsonText);
const workbook = data.clientVars?.collab_client_vars?.initialAttributedText?.text?.[0]?.workbook;
console.log("workbook chars", workbook?.length);
if (workbook) {
  const { inflateSync, gunzipSync, unzipSync } = await import("node:zlib");
  const buffer = Buffer.from(workbook, "base64");
  console.log("buffer bytes", buffer.length, buffer.slice(0, 8).toString("hex"));
  for (const [name, fn] of [["inflate", inflateSync], ["gunzip", gunzipSync], ["unzip", unzipSync]]) {
    try {
      const out = fn(buffer);
      console.log("decoded with", name, "bytes", out.length);
      const text = out.toString("utf8");
      const strings = [...new Set(text.match(/[\u3400-\u9fffA-Za-z0-9·“”《》（）().：:\-—_\s]{2,}/g) || [])]
        .map((s) => s.replace(/\s+/g, " ").trim())
        .filter((s) => /[\u3400-\u9fff]/.test(s));
      console.log(strings.join("\n"));
      break;
    } catch (error) {
      console.error(name, "failed", error.message);
    }
  }
}
