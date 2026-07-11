import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fs from "node:fs";
import path from "node:path";

import { Button } from "@/components/ui/Button";
import { Avatar } from "@/components/ui/Avatar";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ScorePill } from "@/components/ui/ScorePill";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { ListRow } from "@/components/ui/ListRow";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { Tabs } from "@/components/ui/Tabs";
import { Toggle } from "@/components/ui/Toggle";
import { Stepper } from "@/components/ui/Stepper";
import { Dropdown } from "@/components/ui/Dropdown";
import { DataTable } from "@/components/ui/DataTable";

describe("primitives — part A", () => {
  test("button_variants", () => {
    const { rerender } = render(<Button variant="primary">Go</Button>);
    expect(screen.getByRole("button").className).toMatch(/bg-accent-gradient/);
    rerender(<Button variant="chip">Chip</Button>);
    expect(screen.getByRole("button").className).toMatch(/rounded-pill/);
    rerender(
      <Button variant="secondary" disabled>
        Off
      </Button>,
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  test("password_toggle", async () => {
    render(<PasswordInput placeholder="Password" />);
    const input = screen.getByPlaceholderText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
    await userEvent.click(screen.getByRole("button", { name: /show password/i }));
    expect(input.type).toBe("text");
    await userEvent.click(screen.getByRole("button", { name: /hide password/i }));
    expect(input.type).toBe("password");
  });

  test("badges_props_driven", () => {
    render(
      <div>
        <RiskBadge level="high" />
        <StatusBadge label="Needs Review" />
        <ScorePill value={78} />
      </div>,
    );
    expect(screen.getByTestId("risk-badge-high")).toBeInTheDocument();
    expect(screen.getByText("Needs Review")).toBeInTheDocument();
    expect(screen.getByTestId("score-pill")).toHaveTextContent("78/100");
  });

  test("avatar_fallback", () => {
    const { rerender } = render(<Avatar name="Ada Lovelace" />);
    expect(screen.getByLabelText("Ada Lovelace")).toHaveTextContent("AL");
    rerender(<Avatar name="Ada Lovelace" src="/x.png" />);
    expect(screen.getByAltText("Ada Lovelace").tagName).toBe("IMG");
  });

  test("progressbar_value", () => {
    render(<ProgressBar value={35} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "35");
    expect((bar.firstChild as HTMLElement).style.width).toBe("35%");
  });

  test("listrow_slots", () => {
    render(
      <ListRow
        leading={<span data-testid="lead" />}
        title="Report ready"
        subtitle="2m ago"
        trailing={<span data-testid="trail" />}
      />,
    );
    expect(screen.getByTestId("lead")).toBeInTheDocument();
    expect(screen.getByText("Report ready")).toBeInTheDocument();
    expect(screen.getByText("2m ago")).toBeInTheDocument();
    expect(screen.getByTestId("trail")).toBeInTheDocument();
  });

  test("no_baked_mockup_strings", () => {
    const dir = path.join(process.cwd(), "src/components/ui");
    const files = fs.readdirSync(dir).map((f) => fs.readFileSync(path.join(dir, f), "utf8"));
    files.forEach((c) => expect(c).not.toMatch(/Sarah Jenkins|MSA_AcmeCorp|AcmeCorp/));
  });
});

describe("primitives — part B", () => {
  test("stepper_current", () => {
    render(<Stepper steps={["Upload", "AI Analysis", "Review"]} current={1} />);
    const items = screen.getAllByRole("listitem");
    const current = items.filter((li) => li.getAttribute("data-state") === "current");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("AI Analysis");
  });

  test("tabs_variants", async () => {
    const onChange = vi.fn();
    const items = [
      { value: "a", label: "Login" },
      { value: "b", label: "Sign Up" },
    ];
    const { rerender } = render(
      <Tabs items={items} value="a" onChange={onChange} variant="segmented" />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Sign Up" }));
    expect(onChange).toHaveBeenCalledWith("b");
    rerender(<Tabs items={items} value="a" onChange={onChange} variant="underline" />);
    expect(screen.getByRole("tab", { name: "Login" })).toHaveAttribute("aria-selected", "true");
  });

  test("toggle", async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} aria-label="Enable" />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  test("dropdown_select", async () => {
    const onSelect = vi.fn();
    render(
      <Dropdown
        options={[
          { value: "hi", label: "High" },
          { value: "lo", label: "Low" },
        ]}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("option", { name: "Low" }));
    expect(onSelect).toHaveBeenCalledWith("lo");
  });

  test("datatable", async () => {
    const rows = [
      { name: "B.pdf", score: "65" },
      { name: "A.pdf", score: "78" },
    ];
    render(
      <DataTable
        columns={[
          { key: "name", header: "Document", sortable: true },
          { key: "score", header: "Score" },
        ]}
        rows={rows}
        selectable
        actions={() => <button>View</button>}
      />,
    );
    // select-all
    await userEvent.click(screen.getByLabelText("Select all rows"));
    expect((screen.getByLabelText("Select row 0") as HTMLInputElement).checked).toBe(true);
    // sort by Document asc → A.pdf first
    await userEvent.click(screen.getByRole("button", { name: /sort by document/i }));
    const firstRowCells = screen.getAllByRole("row")[1];
    expect(firstRowCells).toHaveTextContent("A.pdf");
    // actions slot
    expect(screen.getAllByRole("button", { name: "View" })).toHaveLength(2);
  });
});
