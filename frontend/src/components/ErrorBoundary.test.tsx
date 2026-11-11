import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never { throw new Error("kaboom"); }

describe("ErrorBoundary", () => {
  it("shows a message instead of a blank page when a child throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary><Boom /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toHaveTextContent(/something went wrong on this page/i);
    expect(screen.getByRole("alert")).toHaveTextContent("kaboom");
  });

  it("renders its children when nothing throws", () => {
    render(<ErrorBoundary><div>fine</div></ErrorBoundary>);
    expect(screen.getByText("fine")).toBeInTheDocument();
  });
});
