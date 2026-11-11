import { describe, expect, it } from "vitest";
import type { GraphPayload } from "../../api/types";
import { layoutGraph, mergeGraphs } from "./layout";

const g1: GraphPayload = {
  nodes: [
    { id: "merchant:M_1", kind: "merchant", label: "M_1", risk_level: "LOW", txn_count: 2 },
    { id: "account:ACC_1", kind: "account", label: "ACC_1", risk_level: "HIGH", txn_count: 3 },
    { id: "device:D_1", kind: "device", label: "D_1", risk_level: "HIGH", txn_count: 3 },
  ],
  edges: [
    { source: "account:ACC_1", target: "device:D_1", kind: "uses_device", weight: 3 },
    { source: "account:ACC_1", target: "merchant:M_1", kind: "pays_merchant", weight: 2 },
  ],
  truncated: false,
};
const g2: GraphPayload = {
  nodes: [
    { id: "account:ACC_1", kind: "account", label: "ACC_1", risk_level: "HIGH", txn_count: 3 },
    { id: "account:ACC_2", kind: "account", label: "ACC_2", risk_level: "LOW", txn_count: 1 },
    { id: "device:D_1", kind: "device", label: "D_1", risk_level: "HIGH", txn_count: 4 },
  ],
  edges: [
    { source: "account:ACC_1", target: "device:D_1", kind: "uses_device", weight: 3 },
    { source: "account:ACC_2", target: "device:D_1", kind: "uses_device", weight: 1 },
  ],
  truncated: true,
};

describe("layoutGraph", () => {
  it("is deterministic regardless of input order and keeps every edge endpoint", () => {
    const a = layoutGraph(g1);
    const b = layoutGraph({ ...g1, nodes: [...g1.nodes].reverse() });
    expect(a.nodes.map((n) => [n.id, n.position])).toEqual(b.nodes.map((n) => [n.id, n.position]));
    const ids = new Set(a.nodes.map((n) => n.id));
    expect(a.edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
    expect(a.edges).toHaveLength(2);
  });

  it("places the three kinds in separate columns", () => {
    const xs = Object.fromEntries(layoutGraph(g1).nodes.map((n) => [n.data.kind, n.position.x]));
    expect(new Set(Object.values(xs)).size).toBe(3);
  });
});

describe("mergeGraphs", () => {
  it("unions nodes and edges without duplicates and ORs the truncated flag", () => {
    const m = mergeGraphs(g1, g2);
    expect(m.nodes.map((n) => n.id).sort()).toEqual(["account:ACC_1", "account:ACC_2", "device:D_1", "merchant:M_1"]);
    expect(m.edges).toHaveLength(3);
    expect(m.truncated).toBe(true);
  });

  it("keeps the higher risk level and the larger count when a node appears twice", () => {
    const low = { ...g1, nodes: [{ ...g1.nodes[1], risk_level: "LOW" as const, txn_count: 1 }], edges: [] };
    const m = mergeGraphs(low, g1);
    const acc = m.nodes.find((n) => n.id === "account:ACC_1")!;
    expect(acc.risk_level).toBe("HIGH");
    expect(acc.txn_count).toBe(3);
  });
});
