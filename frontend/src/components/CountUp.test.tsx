import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtInt } from "../format";
import { CountUp } from "./CountUp";

const motion = (reduce: boolean) => {
  window.matchMedia = vi.fn().mockReturnValue({ matches: reduce, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as never;
};
afterEach(() => { vi.useRealTimers(); delete (window as { matchMedia?: unknown }).matchMedia; });

describe("CountUp", () => {
  it("shows the final value at once when matchMedia is unavailable", () => {
    render(<CountUp value={1234} format={fmtInt} />);
    expect(screen.getByText("1,234")).toBeInTheDocument();
  });

  it("shows the final value at once when the user prefers reduced motion", () => {
    motion(true);
    render(<CountUp value={1234} format={fmtInt} />);
    expect(screen.getByText("1,234")).toBeInTheDocument();
  });

  it("counts up from zero to the final value when motion is allowed", async () => {
    motion(false);
    vi.useFakeTimers();
    render(<CountUp value={1000} format={fmtInt} duration={500} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    const mid = Number(screen.getByTestId("countup").textContent!.replace(/,/g, ""));
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1000);
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(screen.getByText("1,000")).toBeInTheDocument();
  });

  it("lands on the new value when the value changes", async () => {
    motion(false);
    vi.useFakeTimers();
    const { rerender } = render(<CountUp value={10} format={fmtInt} duration={200} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    rerender(<CountUp value={50} format={fmtInt} duration={200} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(screen.getByText("50")).toBeInTheDocument();
  });
});
