import { describe, test, expect, vi } from "vitest";
import { render } from "@testing-library/react";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

import { AppShell } from "@/components/shell/AppShell";
import { getApiClient } from "@/lib/api/provider";

/**
 * Boundary (spec AC-20): the shell/primitives layer renders only placeholder/sample data — it
 * makes NO ApiClient call for live contract data. (Live data arrives with the feature screens
 * in 014–018.)
 */
describe("boundary — no live data fetch from the shell", () => {
  test("shell_no_live_fetch", () => {
    const client = getApiClient();
    const submit = vi.spyOn(client, "submitAnalysis");
    const getJob = vi.spyOn(client, "getJob");
    const openEvents = vi.spyOn(client, "openJobEvents");

    render(
      <AppShell>
        <div>placeholder</div>
      </AppShell>,
    );

    expect(submit).not.toHaveBeenCalled();
    expect(getJob).not.toHaveBeenCalled();
    expect(openEvents).not.toHaveBeenCalled();
  });
});
