export type Role = "viewer" | "analyst" | "admin";
export type Source = "synthetic" | "paysim" | "paypal_sandbox";
export type Level = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
export const LEVELS: Level[] = ["LOW", "MODERATE", "HIGH", "CRITICAL"];
export const HIGH_PLUS: Level[] = ["HIGH", "CRITICAL"];
export type Action = "ALLOW" | "MONITOR" | "REVIEW" | "VERIFY" | "HOLD_RECOMMENDED";

export interface Alert { id: number; txn_external_id: string; level: Level; status: string }

export interface Overview {
  source: Source;
  transactions: { total: number; by_level: Record<Level, number> };
  open_alerts: number; open_cases: number; flagged_clusters: number; suspicious_value: number;
  daily: { date: string; transactions: number; high_plus: number }[];
}

export interface ModelMetrics {
  pr_auc: number | null; roc_auc: number | null; precision: number | null; recall: number | null;
  f1: number | null; threshold: number | null; n_positive: number | null; calibrator: string | null;
  brier_raw: number | null; brier_calibrated: number | null;
}
export interface ModelsSummary {
  version: string; evaluation: string; caveat: string; models: Record<string, ModelMetrics>;
}

export interface TxnListItem {
  external_id: string; ts: string; amount: number; account_id: string; merchant_id: string | null;
  source: Source; risk_level: Level | null; risk_score: number | null; action: Action | null;
  cluster_id: string | null;
}

export interface Contribution { feature: string; value: number; shap: number }
export interface RelatedAccount { account_id: string; links: Record<string, unknown>[] }
export interface TxnDetail {
  details: { transaction: Record<string, string | number | null>; missing_fields: string[]; data_provenance: string };
  risk: {
    risk_score: number; risk_level: Level; recommended_action: Action; calibrated_fraud_probability: number;
    risk_factors: string[]; component_inputs: Record<string, number | boolean>; behaviour_reasons: string[];
    cluster_id: string | null; model_version: string; policy_version: string; note: string;
    alert: { id: number; status: string; level: Level } | null;
  } | null;
  explanation: ({ contributions: Contribution[] } & Record<string, unknown>) | null;
  explanation_unavailable: string | null;
  related: { account_id: string; related: RelatedAccount[]; note: string } | null;
}

export interface CaseSummary {
  id: number; status: string; approved_action: Action | null; n_alerts: number; created_at: string;
}
export interface CaseDetail {
  id: number; status: string; approved_action: Action | null;
  alerts: (Alert & { assessment: {
    risk_score: number; risk_level: Level; action: Action; calibrated_fraud_probability: number;
    factors: string[]; model_version: string; policy_version: string } | null })[];
  notes: { author: string; body: string; ts: string }[];
}
export interface AuditEntry {
  id: number; ts: string; actor: string; action: string; target: string; before: unknown; after: unknown;
}

export interface GraphNode { id: string; kind: "account" | "device" | "merchant"; label: string;
  risk_level: Level | null; txn_count: number }
export interface GraphEdge { source: string; target: string; kind: "uses_device" | "pays_merchant"; weight: number }
export interface GraphPayload { nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean }
export interface ClusterSummary {
  cluster_id: string; n_accounts: number; n_devices: number; n_merchants: number;
  signals: string[]; risk_indicator: number;
}

export interface LiveEvent {
  external_id: string; business_id: string; ts: string; amount: number; account_id: string;
  merchant_id: string | null; source: Source | null; risk_score: number; risk_level: Level;
  recommended_action: Action; calibrated_fraud_probability: number; risk_factors: string[];
  cluster_id: string | null; alert: boolean; late: boolean; latency_ms: number; emitted_at: number;
}
export interface LiveMetrics {
  processed: number; alerts: number; p50_ms: number; p95_ms: number; max_ms: number; dropped: number;
  simulator: { running: boolean; sent: number; errors: number };
}

export interface Finding { claim: string; evidence_ids: string[] }
export interface InvestigationReport {
  case_id: string; transaction: Record<string, unknown>; risk_assessment: Record<string, unknown>;
  summary: string; model_findings: Finding[]; behavioural_findings: Finding[]; graph_findings: Finding[];
  supporting_evidence: Finding[]; contradictory_evidence: Finding[]; missing_information: string[];
  recommended_next_steps: string[]; confidence: string; classification: string; llm_narrative: boolean;
  evidence_ids: string[]; notes: string[];
}
