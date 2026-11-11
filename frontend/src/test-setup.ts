import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  try { sessionStorage.clear(); localStorage.clear(); } catch { /* storage unavailable */ }
});
