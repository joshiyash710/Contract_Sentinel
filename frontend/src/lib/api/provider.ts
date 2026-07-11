import type { ApiClient } from "./client";
import { mockClient } from "./mockProvider";
import { realClient } from "./realProvider";
import { getConfig } from "@/lib/config";

/**
 * The single seam (spec AC-15): returns the mock or real client per one config flag. Swapping
 * a screen mock↔real is this flag — no component edit. Mirrors the single-seam registry
 * pattern feature 011 built for its own 012 swap.
 */
export function getApiClient(): ApiClient {
  return getConfig().provider === "mock" ? mockClient : realClient;
}
