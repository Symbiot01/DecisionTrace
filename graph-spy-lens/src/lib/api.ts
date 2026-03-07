const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) || "http://localhost:8000";

async function fetchApi<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

// Encode natural keys for URL path segments (handles : and /)
export function encodeKey(key: string): string {
  return encodeURIComponent(key);
}

// Types
export interface GraphNode {
  id: string;
  label: string;
  title: string;
  degree: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  confidence: number;
  event_time?: string;
  evidence_excerpt?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: { total_nodes: number; total_edges: number; sampled: boolean };
}

export interface LinkedEntity {
  natural_key: string;
  type: string;
  display_name: string;
}

export interface Evidence {
  excerpt: string | null;
  source_key: string;
  source_url: string | null;
  timestamp: string | null;
}

export interface SearchResult {
  rank: number;
  score: number;
  claim: {
    subject_key: string;
    predicate: string;
    object_key: string;
    confidence: number;
    event_time: string;
  } | null;
  subject_entity: { type: string; natural_key: string; title: string; url: string };
  evidence: Evidence | null;
  linked_entities: LinkedEntity[];
  supersedes?: { natural_key: string; title: string; evidence_excerpt: string; source_url: string } | null;
}

export interface QueryConflict {
  subject_key: string;
  predicate: string;
  conflicting_objects: string[];
  claims: unknown[];
}

export interface SearchResponse {
  question: string;
  intent: string;
  results: SearchResult[];
  conflicts: QueryConflict[];
  metadata: { candidates_found: number; returned: number; processing_ms: number };
}

export interface EntityClaim {
  direction: "incoming" | "outgoing";
  predicate: string;
  other_entity: { natural_key: string; type: string; title: string };
  evidence_excerpt: string;
  confidence: number;
  event_time: string;
  source_url: string;
}

export interface EntityDetail {
  entity: {
    type: string;
    natural_key: string;
    properties: Record<string, unknown>;
    url?: string;
  };
  claims: EntityClaim[];
  supersession_chain?: { natural_key: string; title: string; status: string; event_time: string }[] | null;
  rename_chain?: { natural_key: string; path: string }[] | null;
}

export interface Decision {
  natural_key: string;
  title: string;
  status: string;
  event_time: string;
  evidence_excerpt: string;
  source_key: string;
  source_url: string;
  components: string[];
  supersedes?: string | null;
  superseded_by?: string | null;
}

export interface DecisionsResponse {
  decisions: Decision[];
  total: number;
  limit: number;
  offset: number;
}

export interface ContributorStats {
  total_contributions: number;
  commits: number;
  prs_authored: number;
  reviews_given: number;
  issues_opened: number;
}

export interface Contributor {
  natural_key: string;
  display_name: string;
  aliases: string[];
  url: string;
  stats: ContributorStats;
  decisions_introduced: { natural_key: string; title: string }[];
}

export interface ContributorsResponse {
  contributors: Contributor[];
}

export interface StatsData {
  nodes: Record<string, number>;
  relationships: Record<string, number>;
  processing: { checkpoint_index: number; total_events: number; percent_complete: number };
  top_connected: { natural_key: string; type: string; degree: number }[];
  top_modified_files: { path: string; commit_count: number }[];
}

export interface AskResponse {
  question: string;
  answer: string;
  sources: SearchResult[];
  metadata: { sources_used: number; processing_ms: number };
}

// API functions
export const api = {
  getStats: () => fetchApi<StatsData>("/api/stats"),

  ask: (q: string, limit = 8, min_confidence = 0.4) =>
    fetchApi<AskResponse>("/api/ask", { q, limit, min_confidence }),

  query: (q: string, limit = 10, min_confidence = 0.4) =>
    fetchApi<SearchResponse>("/api/query", { q, limit, min_confidence }),

  getEntity: (key: string) => fetchApi<EntityDetail>(`/api/entity/${encodeKey(key)}`),

  getGraphOverview: (max_nodes = 100) =>
    fetchApi<GraphData>("/api/graph/overview", { max_nodes }),

  getGraphNeighborhood: (key: string, depth = 1, max_nodes = 50) =>
    fetchApi<GraphData>(`/api/graph/neighborhood/${encodeKey(key)}`, { depth, max_nodes }),

  getDecisions: (params?: { component?: string; status?: string; limit?: number; offset?: number }) =>
    fetchApi<DecisionsResponse>("/api/decisions", params as Record<string, string | number | undefined>),

  getContributors: (limit = 20) => fetchApi<ContributorsResponse>("/api/contributors", { limit }),
};
