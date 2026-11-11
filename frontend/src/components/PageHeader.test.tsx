import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("shows the title as the page heading with its subtitle", () => {
    render(<PageHeader title="Overview" subtitle="Portfolio health at a glance" />);
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText("Portfolio health at a glance")).toBeInTheDocument();
  });

  it("renders an actions slot beside the title", () => {
    render(<PageHeader title="Live Monitoring"><button>Pause</button></PageHeader>);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });
});
