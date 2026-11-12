import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup, configure } from "@testing-library/react";

// findBy... gives up after 1 s by default; the first AG Grid render in a busy run can take longer than that
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  try { sessionStorage.clear(); localStorage.clear(); } catch { /* storage unavailable */ }
});

// AG Grid observes element sizes; jsdom has no ResizeObserver
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
