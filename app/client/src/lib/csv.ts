// RFC 4180 CSV parse/serialise. Pure functions (no DOM), unit-tested in csv.test.ts.
//
// Handles: quoted fields, "" escapes, commas and newlines inside quotes, CRLF/LF/CR line ends,
// a UTF-8 BOM, and a trailing newline. Sinhala/Tamil text passes through untouched.

/**
 * Example: parseCsv('a,b\n1,"x, ""y""\nz"\n') -> [["a","b"],["1",'x, "y"\nz']]
 * Throws Error on an unterminated quoted field.
 */
export function parseCsv(input: string): string[][] {
  const text = input.charCodeAt(0) === 0xfeff ? input.slice(1) : input;
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let i = 0;
  let inQuotes = false;
  let fieldStarted = false;

  while (i < text.length) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += c;
      i += 1;
      continue;
    }
    if (c === '"' && !fieldStarted) {
      inQuotes = true;
      fieldStarted = true;
      i += 1;
      continue;
    }
    if (c === ",") {
      row.push(field);
      field = "";
      fieldStarted = false;
      i += 1;
      continue;
    }
    if (c === "\n" || c === "\r") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      fieldStarted = false;
      i += c === "\r" && text[i + 1] === "\n" ? 2 : 1;
      continue;
    }
    field += c;
    fieldStarted = true;
    i += 1;
  }
  if (inQuotes) throw new Error("The CSV has a quoted field that never closes.");
  if (fieldStarted || field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  // Drop blank lines (a row with one empty field).
  return rows.filter((r) => !(r.length === 1 && r[0] === ""));
}

/** Example: csvRecords('id,text\n1,hi') -> { header: ["id","text"], records: [{id:"1", text:"hi"}] } */
export function csvRecords(input: string): { header: string[]; records: Record<string, string>[] } {
  const rows = parseCsv(input);
  const [first, ...rest] = rows;
  if (!first) return { header: [], records: [] };
  const header = first.map((h) => h.trim());
  const records = rest.map((r) => Object.fromEntries(header.map((h, idx) => [h, r[idx] ?? ""])));
  return { header, records };
}

function escapeCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  return /[",\r\n]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * Example: toCsv(["a","b"], [{a: 1, b: "x,y"}]) -> '﻿a,b\r\n1,"x,y"\r\n'
 * Starts with a BOM so Excel opens Sinhala/Tamil text as UTF-8.
 */
export function toCsv(columns: string[], records: Record<string, unknown>[]): string {
  const lines = [columns.map(escapeCell).join(",")];
  for (const r of records) lines.push(columns.map((c) => escapeCell(r[c])).join(","));
  return "﻿" + lines.join("\r\n") + "\r\n";
}
