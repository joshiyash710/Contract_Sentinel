/**
 * Frontend runtime config (spec 013 §2.4). The two knobs are env-driven, never hardcoded
 * (constitution §3). `apiBaseUrl` defaults to same-origin ("") which routes through the
 * Next.js dev proxy (next.config.mjs). `provider` selects the mock vs real API client.
 */
export interface AppConfig {
  apiBaseUrl: string;
  provider: "mock" | "real";
}

export function getConfig(): AppConfig {
  return {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
    provider: (process.env.NEXT_PUBLIC_API_PROVIDER as "mock" | "real") ?? "mock",
  };
}
