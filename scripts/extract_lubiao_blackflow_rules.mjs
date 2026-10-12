import { writeFileSync } from "node:fs";

const pageUrl = "https://www.lubiao.wiki/tools/blackstream-route";
const html = await fetch(pageUrl).then((response) => response.text());

const chunkUrls = [...html.matchAll(/(?:href|src)="([^"]+\.js)"/g)]
  .map((match) => new URL(match[1], pageUrl).href);

let routeChunk = null;
let routeCode = "";
for (const url of chunkUrls) {
  const code = await fetch(url).then((response) => response.text());
  if (
    code.includes("节点预测功能说明") &&
    code.includes("各层节点距起点徒步最短距离范围") &&
    code.includes("各层节点可出现数量范围")
  ) {
    routeChunk = url;
    routeCode = code;
    break;
  }
}

if (!routeChunk) {
  throw new Error("Could not locate Lubiao route rule chunk");
}

const start = routeCode.indexOf("al=");
const end = routeCode.indexOf("const ul=", start);
if (start < 0 || end < 0) {
  throw new Error("Could not locate rule table constants");
}

const constantsBlock = routeCode.slice(start, end);

function extractAssignment(source, name) {
  const marker = `${name}=`;
  const startIndex = source.indexOf(marker);
  if (startIndex < 0) throw new Error(`Missing ${name}`);
  const expressionStart = startIndex + marker.length;
  let index = expressionStart;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (; index < source.length; index += 1) {
    const char = source[index];
    if (inString) {
      if (escape) escape = false;
      else if (char === "\\") escape = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === "[" || char === "{" || char === "(") depth += 1;
    else if (char === "]" || char === "}" || char === ")") depth -= 1;
    if (index > expressionStart && depth === 0) {
      const next = source[index + 1];
      if (next === "," || next === ";") {
        index += 1;
        break;
      }
    }
  }
  return source.slice(expressionStart, index);
}

function normalizeJsExpression(expression) {
  return expression
    .replaceAll("S(", "range(")
    .replaceAll("f(", "range(")
    .replaceAll("qt(", "oneOf(")
    .replaceAll("Ao", "unknown");
}

function extractConst(name) {
  return extractAssignment(constantsBlock, name);
}

function evaluateExpression(expression) {
  const range = (minimum, maximum = minimum) => ({ kind: "range", minimum, maximum });
  const oneOf = (...values) => ({ kind: "oneOf", values });
  const unknown = { kind: "unknown" };
  return Function("range", "oneOf", "unknown", `return (${normalizeJsExpression(expression)});`)(
    range,
    oneOf,
    unknown,
  );
}

function formatValue(value) {
  if (value == null) return null;
  if (value.kind === "range") return value;
  if (value.kind === "oneOf") return value;
  if (value.kind === "unknown") return value;
  return value;
}

function tableFromRows(rows, columns) {
  return rows.map((row) => ({
    label: row.label,
    nodeType: row.nodeType ?? null,
    values: Object.fromEntries(
      row.values.map((value, index) => [columns[index], formatValue(value)]),
    ),
  }));
}

const layerColumns = evaluateExpression(extractConst("Fo"));
const distanceColumns = evaluateExpression(extractConst("Do"));
const layerNodeTypes = evaluateExpression(extractConst("sl"));
const countRows = evaluateExpression(extractConst("Go"));
const distanceRows = evaluateExpression(extractConst("Wo"));
const countRanges = tableFromRows(countRows, layerColumns);
const fifthFloorClearing = countRanges.find((row) => row.label === "林间空地")?.values.V;
if (fifthFloorClearing?.kind !== "range" || !Number.isInteger(fifthFloorClearing.maximum) || fifthFloorClearing.maximum < 17) {
  throw new Error("Route data predates the fifth-floor clearing maximum of 17; refusing to overwrite local rules");
}
const templateExpression = extractAssignment(routeCode, "const _l");
const floorTemplates = Function(
  "_e",
  `return (${templateExpression});`,
)(
  (template) => {
    const occupied = new Set(template.occupiedSlots.map(([row, column]) => `${row}:${column}`));
    const excluded = new Set(
      (template.excludedEdges ?? []).map((edge) => edge.map(([row, column]) => `${row}:${column}`).sort().join("|")),
    );
    const edges = [];
    for (const slot of template.occupiedSlots) {
      const [row, column] = slot;
      for (const neighbor of [
        [row + 1, column],
        [row, column + 1],
      ]) {
        const neighborKey = `${neighbor[0]}:${neighbor[1]}`;
        const edgeKey = [`${row}:${column}`, neighborKey].sort().join("|");
        if (occupied.has(neighborKey) && !excluded.has(edgeKey)) edges.push([slot, neighbor]);
      }
    }
    return { ...template, edges };
  },
);

const templateCounts = {};
const gridShapes = {};
const mainLayerTemplateCounts = {};
const mainLayerGridShapes = {};
const specialTemplates = [];
for (const template of floorTemplates) {
  const layer = String(template.layerIndex + 1);
  templateCounts[layer] = (templateCounts[layer] ?? 0) + 1;
  (gridShapes[layer] ??= new Set()).add(`${template.gridShape[0]}x${template.gridShape[1]}`);
  if (template.layerIndex >= 0 && template.layerIndex <= 4) {
    mainLayerTemplateCounts[layer] = (mainLayerTemplateCounts[layer] ?? 0) + 1;
    (mainLayerGridShapes[layer] ??= new Set()).add(`${template.gridShape[0]}x${template.gridShape[1]}`);
  } else {
    specialTemplates.push({
      id: template.id,
      sourceId: template.sourceId,
      internalLayerIndex: template.layerIndex,
      gridShape: template.gridShape,
      terminalType: template.terminalType ?? null,
      utopiaPortal: template.utopiaPortal ?? null,
    });
  }
}

const output = {
  schemaVersion: 1,
  source: {
    name: "路标档案馆 黑流树海地图规划",
    pageUrl,
    routeChunk,
    extractedAt: new Date().toISOString(),
    ruleVersion: routeCode.match(/al="([^"]+)"/)?.[1] ?? null,
  },
  notes: [
    "最短距离只沿地图上的普通连线，从起点开始数边；不计算行动力，也不考虑加工品和曲折密道。",
    "“10+”在数据中表示 maximum 为 null；“未定”表示 kind 为 unknown；null 表示该层不出现或不适用。",
    "第四层默认使用 IV；启用 IV 追忆规则时，距离表使用 IV追忆列，两列不混合。",
    "节点预测表示按现有信息仍可能为这些类型，不表示候选概率相同。",
  ],
  predictionMethods: [
    {
      id: "construction_template",
      description: "拖入起点或险路节点后，可尝试识别已收录的地图构造；模板中位置固定的必出节点直接显示，不参加未知节点轮播。",
    },
    {
      id: "ideal_source_center",
      description: "选择“希望的沃土”理念时，理想源中心保留原节点，也可以为空地；选择其他理念时，中心按紧急作战显示。",
    },
    {
      id: "unknown_node_candidates",
      description: "未知的诡秘/凶戾会综合未知类别、本层可出现类型、距起点徒步最短距离、节点数量上限和已录入机制证据；I 层未知的诡秘不将诡意行商列为候选。",
    },
    {
      id: "settlement_candidates",
      description: "“居民”据点只会在 II、IV、V 层的凶戾未知节点中预测，并仍须满足该层数量和距起点范围；每个流窜“居民”标记须在候选据点 1-5 步内。",
    },
  ],
  layerNodeTypes,
  countRanges,
  shortestDistanceFromStart: tableFromRows(distanceRows, distanceColumns),
  templateSummary: {
    mainLayers: {
      templateCounts: mainLayerTemplateCounts,
      gridShapes: Object.fromEntries(
        Object.entries(mainLayerGridShapes).map(([layer, shapes]) => [layer, [...shapes]]),
      ),
    },
    allTemplatesByInternalLayer: {
      note: "普通探索主层为 layerIndex 0-4，即 I-V；更高 internalLayerIndex 为工具收录的特殊/树洞等构造。",
      templateCounts,
      gridShapes: Object.fromEntries(
        Object.entries(gridShapes).map(([layer, shapes]) => [layer, [...shapes]]),
      ),
    },
    templateCounts,
    gridShapes: Object.fromEntries(
      Object.entries(gridShapes).map(([layer, shapes]) => [layer, [...shapes]]),
    ),
    specialTemplates,
  },
  floorTemplates,
};

writeFileSync("data/blackflow_node_generation_rules.json", `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(`wrote data/blackflow_node_generation_rules.json from ${routeChunk}`);
console.log(`ruleVersion=${output.source.ruleVersion}`);
