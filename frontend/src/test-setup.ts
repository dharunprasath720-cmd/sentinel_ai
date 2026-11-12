import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  try { sessionStorage.clear(); localStorage.clear(); } catch { /* storage unavailable */ }
});

// AG Grid observes element sizes; jsdom has no ResizeObserver
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
