import { apiRequest } from "./client";
import {
  overviewSchema,
  paperDetailSchema,
  paperListSchema,
  type OverviewResponse,
  type PaperDetailResponse,
  type PaperListResponse,
} from "./schema";


export interface PaperQuery {
  page?: number;
  page_size?: number;
  search?: string;
  doi?: string;
  target?: string;
  has_lineage?: "true" | "false";
  relation_status?: string;
  structure_state?: string;
  review_status?: string;
  sort?: "manifest" | "paper_id" | "-paper_id" | "title" | "-title";
}

function queryString(query: PaperQuery): string {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") parameters.set(key, String(value));
  }
  const encoded = parameters.toString();
  return encoded ? `?${encoded}` : "";
}

export function fetchOverview(): Promise<OverviewResponse> {
  return apiRequest("/api/v1/published/overview", overviewSchema);
}

export function fetchPapers(query: PaperQuery): Promise<PaperListResponse> {
  return apiRequest(`/api/v1/papers${queryString(query)}`, paperListSchema);
}

export function fetchPaperDetail(paperId: string): Promise<PaperDetailResponse> {
  return apiRequest(
    `/api/v1/papers/${encodeURIComponent(paperId)}`,
    paperDetailSchema,
  );
}
