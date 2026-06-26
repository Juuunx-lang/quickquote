import * as XLSX from "xlsx";

type ExcelCell = string | number | boolean | Date | null | undefined;
type ExcelRow = ExcelCell[];

const EMPTY_TEXT = "无";

const NAME_KEYWORDS = [
  "名称",
  "商品名称",
  "产品名称",
  "物料名称",
  "物料名",
  "物品名称",
  "物品名",
  "货品名称",
  "货品名",
  "品名",
  "name",
  "product",
];

const SPEC_KEYWORDS = [
  "规格",
  "型号",
  "规格型号",
  "采购规格",
  "采购型号",
  "申购型号",
  "货品型号",
  "货品规格",
  "model",
  "spec",
  "specification",
];

function normalizeCell(value: ExcelCell): string {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).trim();
}

function findColumn(headers: string[], keywords: string[]): number {
  return headers.findIndex((header) => {
    const normalized = header.trim().toLowerCase();
    return normalized.length > 0 && keywords.some((keyword) => normalized.includes(keyword.toLowerCase()));
  });
}

function findHeaderRow(rows: ExcelRow[]): number {
  const maxScanRows = Math.min(rows.length, 10);
  for (let index = 0; index < maxScanRows; index += 1) {
    const headers = (rows[index] || []).map(normalizeCell);
    const hasName = findColumn(headers, NAME_KEYWORDS) >= 0;
    const hasSpec = findColumn(headers, SPEC_KEYWORDS) >= 0;
    if (hasName || hasSpec) return index;
  }
  return 0;
}

function buildBackendRow(name: string, spec: string): string {
  return `名称：${name || EMPTY_TEXT} 规格：${spec || EMPTY_TEXT}`;
}

export async function parseExcelToItems(file: File): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = (event) => {
      try {
        const data = new Uint8Array(event.target?.result as ArrayBuffer);
        const workbook = XLSX.read(data, { type: "array" });
        const firstSheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[firstSheetName];
        const rows = XLSX.utils.sheet_to_json<ExcelRow>(worksheet, { header: 1, blankrows: false });

        if (rows.length <= 1) {
          resolve([]);
          return;
        }

        const headerRowIndex = findHeaderRow(rows);
        const headers = (rows[headerRowIndex] || []).map(normalizeCell);
        const nameCol = findColumn(headers, NAME_KEYWORDS);
        const specCol = findColumn(headers, SPEC_KEYWORDS);
        const fallbackNameCol = nameCol >= 0 ? nameCol : 0;
        const fallbackSpecCol = specCol >= 0 && specCol !== fallbackNameCol ? specCol : 1;

        const results: string[] = [];
        for (let index = headerRowIndex + 1; index < rows.length; index += 1) {
          const row = rows[index];
          if (!row) continue;

          const name = normalizeCell(row[fallbackNameCol]);
          const spec = fallbackSpecCol >= 0 && fallbackSpecCol !== fallbackNameCol ? normalizeCell(row[fallbackSpecCol]) : "";

          if (!name && !spec) continue;
          results.push(buildBackendRow(name, spec));
        }

        resolve(Array.from(new Set(results)));
      } catch (error) {
        reject(error);
      }
    };

    reader.onerror = (error) => reject(error);
    reader.readAsArrayBuffer(file);
  });
}
