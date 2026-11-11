import { describe, expect, it } from "vitest";
import { canAct } from "./roles";

describe("canAct", () => {
  it("is true for analyst and admin only", () => {
    expect(canAct("analyst")).toBe(true);
    expect(canAct("admin")).toBe(true);
    expect(canAct("viewer")).toBe(false);
    expect(canAct(null)).toBe(false);
  });
});
