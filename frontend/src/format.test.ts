import { describe, expect, it } from "vitest";
import { fmt3, fmtTime } from "./format";

describe("fmtTime", () => {
  it("treats a timestamp without a zone as UTC, so every viewer sees the same instant", () => {
    expect(fmtTime("2026-01-22T04:49:53.655126")).toBe(fmtTime("2026-01-22T04:49:53.655126Z"));
  });

  it("respects an explicit offset", () => {
    expect(fmtTime("2026-01-22T10:19:53+05:30")).toBe(fmtTime("2026-01-22T04:49:53Z"));
  });

  it("returns the input when it is not a date", () => {
    expect(fmtTime("not a date")).toBe("not a date");
  });
});

describe("fmt3", () => {
  it("never prints NaN", () => {
    expect(fmt3(null)).toBe("—");
    expect(fmt3(Number.NaN)).toBe("—");
    expect(fmt3(0.4789)).toBe("0.479");
  });
});
