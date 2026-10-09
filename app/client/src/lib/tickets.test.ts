import { describe, expect, it } from "vitest";
import { CATEGORY, RESULT_COLUMNS, flattenResult, loadTickets, validateTicket } from "./tickets";

describe("validateTicket", () => {
  it("mirrors the contract rules", () => {
    expect(validateTicket({ channel: "chat", text: "hi" })).toEqual([]);
    const p = validateTicket({ channel: "fax", text: "   ", subject: "x".repeat(501), ticket_id: "y".repeat(65) });
    expect(p.map((x) => x.field)).toEqual(["channel", "text", "subject", "ticket_id"]);
    expect(validateTicket({ channel: "email", text: "a".repeat(10_001) })[0]?.issue).toMatch(/longer than/);
  });
});

describe("loadTickets", () => {
  it("reports file row numbers, duplicate and missing ids", () => {
    const { rows, problems, total } = loadTickets("t.csv", "channel,text,ticket_id\nchat,hi,A\nfax,,A\nemail,ok,\n");
    expect(total).toBe(3);
    expect(rows.map((r) => r.row)).toEqual([2]);
    expect(problems).toEqual([
      { row: 3, field: "channel", issue: '"fax" is not chat, email or call_transcript' },
      { row: 3, field: "text", issue: "is empty" },
      { row: 3, field: "ticket_id", issue: '"A" repeats row 2' },
      { row: 4, field: "ticket_id", issue: "is empty (other rows have one)" },
    ]);
  });
  it("generates ids when the column is absent and accepts header case variants", () => {
    const { rows } = loadTickets("t.csv", "Channel,Text\nCHAT,hello\n");
    expect(rows[0]?.ticket).toEqual({ ticket_id: "row-2", channel: "chat", subject: "", text: "hello" });
  });
  it("reads JSONL and JSON ({tickets: [...]})", () => {
    expect(loadTickets("t.jsonl", '{"channel":"chat","text":"x"}\n{"channel":"email","text":"y","subject":"s"}\n').rows).toHaveLength(2);
    expect(loadTickets("t.json", '{"tickets":[{"channel":"chat","text":"x"}]}').rows[0]?.row).toBe(1);
  });
  it("explains unusable files", () => {
    expect(() => loadTickets("t.csv", "foo,bar\n1,2")).toThrow(/channel.*text/);
    expect(() => loadTickets("t.json", "{nope")).toThrow(/not valid JSON/);
  });
});

describe("flattenResult", () => {
  it("keeps source columns and appends prediction columns", () => {
    const out = flattenResult({ ticket_id: "A", language: "si" }, {
      ticket_id: "A", category: "delivery_delay", secondary_category: null, team: "Delivery Operations",
      is_urgent: false, confidence: 0.91234, model_version: "v1", needs_human_review: false,
    });
    expect(out).toMatchObject({ ticket_id: "A", language: "si", secondary_category: "", confidence: "0.9123", is_urgent: "false" });
    expect(RESULT_COLUMNS.every((c) => c in out)).toBe(true);
  });
  it("team table covers all 11 categories", () => {
    expect(Object.keys(CATEGORY)).toHaveLength(11);
  });
});
