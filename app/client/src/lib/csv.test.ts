import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { csvRecords, parseCsv, toCsv } from "./csv";

describe("parseCsv", () => {
  it("handles quotes, escaped quotes, embedded newlines, CRLF and blank lines", () => {
    expect(parseCsv('a,b\r\n1,"x, ""y""\nz"\r\n\r\n2,\n')).toEqual([["a", "b"], ["1", 'x, "y"\nz'], ["2", ""]]);
  });
  it("strips a BOM and keeps Sinhala/Tamil text intact", () => {
    expect(parseCsv("﻿text\nමගේ බෑග් එක\nஎன் ஆர்டர்")).toEqual([["text"], ["මගේ බෑග් එක"], ["என் ஆர்டர்"]]);
  });
  it("rejects an unterminated quote", () => {
    expect(() => parseCsv('a\n"open')).toThrow(/never closes/);
  });
});

describe("toCsv", () => {
  it("round-trips through csvRecords", () => {
    const records = [{ id: "1", text: 'a "quoted", multi\nline' }, { id: "2", text: " padded " }];
    const out = toCsv(["id", "text"], records);
    expect(out.startsWith("﻿")).toBe(true);
    expect(csvRecords(out).records).toEqual(records);
  });
});

// The competition CSV (not in git): every row must parse like Python's csv module would.
const DATASET = new URL("../../../../Resources/TensorForge 2.0 - MVP Resources DataSet/validation.csv", import.meta.url);
describe.skipIf(!existsSync(DATASET))("competition validation.csv", () => {
  it("parses all 800 rows with the expected columns", () => {
    const { header, records } = csvRecords(readFileSync(DATASET, "utf8"));
    expect(header).toEqual(["ticket_id", "channel", "subject", "text", "language", "category", "secondary_category", "is_urgent"]);
    expect(records).toHaveLength(800);
    expect(records.filter((r) => r.text?.includes("\n")).length).toBeGreaterThan(500);
    expect(records.every((r) => ["chat", "email", "call_transcript"].includes(r.channel ?? ""))).toBe(true);
  });
});
