// Types mirroring the server's public contract. No proprietary logic here.

export type MemoFormat = "md" | "pdf" | "docx";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface TickersResponse {
  sector_tickers: string[];
  competitor_map: Record<string, string[]>;
}

export interface MemoJob {
  job_id: string;
  ticker: string;
  status: "queued" | "processing" | "complete" | "failed";
  progress: number;
  error: string | null;
  formats: string[];
}

export interface UsageResponse {
  plan: string;
  billing_period: string;
  used: number;
  quota: number | null;
}

export interface ApiKeyCreated {
  api_key: string;
  prefix: string;
  name: string;
}

export interface ApiKeyInfo {
  prefix: string;
  name: string;
  created_at: string;
  revoked: boolean;
}

export interface Health {
  status: string;
  auth_mode: "license" | "saas";
}
