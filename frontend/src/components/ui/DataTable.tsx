"use client";

import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";

export interface Column<T> {
  key: string;
  header: string;
  sortable?: boolean;
  /** Custom cell renderer; defaults to `String(row[key])`. */
  render?: (row: T) => ReactNode;
}

interface DataTableProps<T extends Record<string, unknown>> {
  columns: Column<T>[];
  rows: T[];
  /** Enables row-select + select-all checkboxes. */
  selectable?: boolean;
  /** Per-row actions slot (screen 12 "View/Compare/Download"). */
  actions?: (row: T) => ReactNode;
  rowKey?: (row: T, index: number) => string;
  className?: string;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

// Generic data table (screen 12 history). Sortable headers, row-select/select-all, per-row
// actions slot — all props-driven, no baked strings (spec AC-12b, EC-5).
export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  selectable = false,
  actions,
  rowKey = (_r, i) => String(i),
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const sortedRows = (() => {
    if (!sort) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return copy;
  })();

  const toggleSort = (key: string) =>
    setSort((s) =>
      s && s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );

  const allKeys = sortedRows.map((r, i) => rowKey(r, i));
  const allSelected = allKeys.length > 0 && allKeys.every((k) => selected.has(k));
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(allKeys));
  const toggleOne = (k: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });

  return (
    <table className={clsx("w-full text-left text-body", className)}>
      <thead>
        <tr className="border-b border-subtle text-text-secondary">
          {selectable && (
            <th className="w-10 px-3 py-2.5">
              <input
                type="checkbox"
                aria-label="Select all rows"
                checked={allSelected}
                onChange={toggleAll}
              />
            </th>
          )}
          {columns.map((col) => (
            <th key={col.key} className="px-3 py-2.5 font-medium">
              {col.sortable ? (
                <button
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  aria-label={`Sort by ${col.header}`}
                  className="inline-flex items-center gap-1 hover:text-text-primary"
                >
                  {col.header}
                  {sort?.key === col.key &&
                    (sort.dir === "asc" ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                </button>
              ) : (
                col.header
              )}
            </th>
          ))}
          {actions && <th className="px-3 py-2.5 font-medium">Actions</th>}
        </tr>
      </thead>
      <tbody>
        {sortedRows.map((row, i) => {
          const k = rowKey(row, i);
          return (
            <tr key={k} className="border-b border-subtle/60">
              {selectable && (
                <td className="px-3 py-2.5">
                  <input
                    type="checkbox"
                    aria-label={`Select row ${k}`}
                    checked={selected.has(k)}
                    onChange={() => toggleOne(k)}
                  />
                </td>
              )}
              {columns.map((col) => (
                <td key={col.key} className="px-3 py-2.5 text-text-primary">
                  {col.render ? col.render(row) : String(row[col.key] ?? "")}
                </td>
              ))}
              {actions && <td className="px-3 py-2.5">{actions(row)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
