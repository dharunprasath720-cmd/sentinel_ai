import { LEVELS, type GraphNode, type GraphPayload } from "../../api/types";

export interface FlowNode { id: string; position: { x: number; y: number }; data: GraphNode }
export interface FlowEdge { id: string; source: string; target: string; label: string }

const COLUMN_X: Record<GraphNode["kind"], number> = { account: 0, device: 340, merchant: 680 };
const ROW_HEIGHT = 84;

/** Pure and deterministic: one column per node kind, rows ordered by id, so the same graph always
 *  lays out the same way whatever order the server listed it in. */
export function layoutGraph(g: GraphPayload): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodes: FlowNode[] = [];
  for (const kind of Object.keys(COLUMN_X) as GraphNode["kind"][]) {
    g.nodes.filter((n) => n.kind === kind).sort((a, b) => a.id.localeCompare(b.id))
      .forEach((n, i) => nodes.push({ id: n.id, position: { x: COLUMN_X[kind], y: i * ROW_HEIGHT }, data: n }));
  }
  const ids = new Set(nodes.map((n) => n.id));
  const edges = g.edges.filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => ({ id: `${e.source}|${e.target}|${e.kind}`, source: e.source, target: e.target, label: String(e.weight) }));
  return { nodes, edges };
}

const rank = (l: GraphNode["risk_level"]) => (l === null ? -1 : LEVELS.indexOf(l));

/** Union of two graphs: a node seen twice keeps its higher risk level and larger count. */
export function mergeGraphs(a: GraphPayload, b: GraphPayload): GraphPayload {
  const nodes = new Map<string, GraphNode>();
  for (const n of [...a.nodes, ...b.nodes]) {
    const prev = nodes.get(n.id);
    nodes.set(n.id, !prev ? n : {
      ...prev,
      risk_level: rank(n.risk_level) > rank(prev.risk_level) ? n.risk_level : prev.risk_level,
      txn_count: Math.max(prev.txn_count, n.txn_count),
    });
  }
  const edges = new Map<string, GraphPayload["edges"][number]>();
  for (const e of [...a.edges, ...b.edges]) {
    const key = `${e.source}|${e.target}|${e.kind}`;
    const prev = edges.get(key);
    edges.set(key, prev ? { ...prev, weight: Math.max(prev.weight, e.weight) } : e);
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()], truncated: a.truncated || b.truncated };
}
