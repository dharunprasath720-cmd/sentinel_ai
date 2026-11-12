import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { GraphPayload, Level } from "../../api/types";
import { layoutGraph } from "./layout";

const COLOUR: Record<Level, string> = {
  LOW: "#3ecf8e", MODERATE: "#f5b942", HIGH: "#ff8a4c", CRITICAL: "#ff5d6c",
};
const SHAPE = { account: "▲ account", device: "■ device", merchant: "● merchant" } as const;

/** React Flow canvas. Risk is shown by border colour AND by the printed level; node kind by a
 *  symbol and word. Clicking an account node asks the parent to expand its neighbourhood. */
export function GraphCanvas({ graph, onExpand }: { graph: GraphPayload; onExpand: (accountId: string) => void }) {
  const { nodes, edges } = useMemo(() => {
    const laid = layoutGraph(graph);
    const nodes: Node[] = laid.nodes.map((n) => ({
      id: n.id, position: n.position,
      data: {
        kind: n.data.kind, accountId: n.data.label,
        label: (
          <div>
            <strong>{n.data.label}</strong>
            <div style={{ fontSize: 11 }}>{SHAPE[n.data.kind]} · {n.data.risk_level ?? "no risk level"} · {n.data.txn_count} txns</div>
          </div>
        ),
      },
      style: {
        border: `2px solid ${n.data.risk_level ? COLOUR[n.data.risk_level] : "#475569"}`,
        background: "#16223a", color: "#e8edf7", borderRadius: n.data.kind === "merchant" ? 24 : n.data.kind === "device" ? 4 : 10,
        width: 220,
      },
    }));
    const edges: Edge[] = laid.edges.map((e) => ({ ...e, style: { stroke: "#5b6b8c" }, labelStyle: { fill: "#94a3c0" } }));
    return { nodes, edges };
  }, [graph]);

  return (
    <div className="graph-canvas" aria-label="Graph canvas">
      <ReactFlow nodes={nodes} edges={edges} fitView colorMode="dark" nodesConnectable={false}
        onNodeClick={(_, node) => { if (node.data.kind === "account") onExpand(String(node.data.accountId)); }}>
        <Background /><Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
