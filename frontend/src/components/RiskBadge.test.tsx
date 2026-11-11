import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RiskBadge } from "./RiskBadge";

describe("RiskBadge", () => {
  it.each(["LOW", "MODERATE", "HIGH", "CRITICAL"] as const)("shows the %s level as text", (level) => {
    render(<RiskBadge level={level} />);
    expect(screen.getByText(level)).toBeInTheDocument();
  });

  it("shows a dash when there is no level", () => {
    render(<RiskBadge level={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
