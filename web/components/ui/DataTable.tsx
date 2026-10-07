"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { EmptyState } from "./EmptyState";

export interface Column<T> {
  key: string;
  header: string;
  /** Custom cell renderer. Defaults to the column's value. */
  cell?: (row: T) => ReactNode;
  /** Value used for display fallback and for local sorting/filtering. Defaults to `row[key]`. */
  value?: (row: T) => string | number | null | undefined;
  sortable?: boolean;
  align?: "left" | "right";
  className?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export interface PageState {
  /** Zero-based page index. */
  index: number;
  size: number;
  /** Total matching rows on the server. */
  total: number;
}

/**
 * Controlled table. Sorting, filtering, and paging are reported through callbacks so the caller can
 * push them to the API — the table never needs the full dataset in memory (principle 9).
 * For small in-memory lists, use `useLocalTable`.
 */
export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  filter?: string;
  onFilterChange?: (value: string) => void;
  filterPlaceholder?: string;
  page?: PageState;
  onPageChange?: (index: number) => void;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  /** Rendered in place of rows when there are none. */
  empty?: ReactNode;
  toolbar?: ReactNode;
  caption?: string;
  className?: string;
}

export function nextSort(current: SortState | null | undefined, key: string): SortState {
  if (current?.key === key) return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  return { key, dir: "asc" };
}

function columnValue<T>(col: Column<T>, row: T): string | number | null | undefined {
  if (col.value) return col.value(row);
  const v = (row as Record<string, unknown>)[col.key];
  return typeof v === "string" || typeof v === "number" ? v : v == null ? v : String(v);
}

/** Filter and sort rows in memory. Only for small lists — large tables should query the API. */
export function applyLocalQuery<T>(
  rows: T[],
  columns: Column<T>[],
  { sort, filter }: { sort?: SortState | null; filter?: string },
): T[] {
  let out = rows;
  const q = filter?.trim().toLowerCase();
  if (q) {
    out = out.filter((row) =>
      columns.some((c) => {
        const v = columnValue(c, row);
        return v != null && String(v).toLowerCase().includes(q);
      }),
    );
  }
  const col = sort ? columns.find((c) => c.key === sort.key) : undefined;
  if (sort && col) {
    const dir = sort.dir === "asc" ? 1 : -1;
    out = [...out].sort((a, b) => {
      const va = columnValue(col, a);
      const vb = columnValue(col, b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1; // nulls last in both directions
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
    });
  }
  return out;
}

/** Local state wiring for DataTable over an in-memory list. */
export function useLocalTable<T>(rows: T[], columns: Column<T>[], pageSize = 25) {
  const [sort, setSort] = useState<SortState | null>(null);
  const [filter, setFilter] = useState("");
  const [index, setIndex] = useState(0);
  const matched = useMemo(() => applyLocalQuery(rows, columns, { sort, filter }), [rows, columns, sort, filter]);
  const pageCount = Math.max(1, Math.ceil(matched.length / pageSize));
  const safeIndex = Math.min(index, pageCount - 1);
  return {
    rows: matched.slice(safeIndex * pageSize, (safeIndex + 1) * pageSize),
    sort,
    onSortChange: setSort,
    filter,
    onFilterChange: (v: string) => {
      setFilter(v);
      setIndex(0);
    },
    page: { index: safeIndex, size: pageSize, total: matched.length },
    onPageChange: setIndex,
  };
}

const numberFormat = new Intl.NumberFormat("en-US");

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  filter,
  onFilterChange,
  filterPlaceholder = "Filter",
  page,
  onPageChange,
  onRowClick,
  loading,
  empty,
  toolbar,
  caption,
  className,
}: DataTableProps<T>) {
  const hasToolbar = onFilterChange || toolbar;
  const first = page ? page.index * page.size + 1 : 0;
  const last = page ? Math.min(page.total, (page.index + 1) * page.size) : 0;
  const pageCount = page ? Math.max(1, Math.ceil(page.total / page.size)) : 1;

  return (
    <div className={cn("min-w-0 overflow-hidden rounded-lg border border-line bg-canvas", className)}>
      {hasToolbar ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          {onFilterChange ? (
            <input
              type="search"
              value={filter ?? ""}
              onChange={(e) => onFilterChange(e.target.value)}
              placeholder={filterPlaceholder}
              aria-label={filterPlaceholder}
              className="h-[30px] w-60 max-w-full rounded-md border border-line-strong bg-canvas px-2.5 placeholder:text-ink-3"
            />
          ) : null}
          {toolbar ? <div className="ml-auto flex flex-wrap items-center gap-2">{toolbar}</div> : null}
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]" aria-busy={loading || undefined}>
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead>
            <tr>
              {columns.map((col) => {
                const active = sort?.key === col.key;
                const ariaSort = active ? (sort!.dir === "asc" ? "ascending" : "descending") : col.sortable ? "none" : undefined;
                const Icon = !active ? ChevronsUpDown : sort!.dir === "asc" ? ArrowUp : ArrowDown;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={ariaSort}
                    className={cn(
                      "h-[34px] whitespace-nowrap border-b border-line bg-subtle px-3 text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3",
                      col.align === "right" ? "text-right" : "text-left",
                    )}
                  >
                    {col.sortable && onSortChange ? (
                      <button
                        type="button"
                        onClick={() => onSortChange(nextSort(sort, col.key))}
                        className={cn("inline-flex items-center gap-1 uppercase hover:text-ink", active && "text-ink")}
                      >
                        {col.header}
                        <Icon aria-hidden className={cn("size-3", !active && "opacity-50")} />
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>
                  {loading ? (
                    <div className="px-4 py-6 text-center text-ink-3">Loading…</div>
                  ) : (
                    (empty ?? <EmptyState size="compact" title={filter ? "No rows match this filter" : "No data yet"} />)
                  )}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn("border-b border-line last:border-b-0", onRowClick && "cursor-pointer hover:bg-hover")}
                >
                  {columns.map((col) => {
                    const content = col.cell ? col.cell(row) : columnValue(col, row);
                    return (
                      <td
                        key={col.key}
                        className={cn(
                          "px-3 py-2.5 align-middle",
                          col.align === "right" && "whitespace-nowrap text-right tabular-nums",
                          col.className,
                        )}
                      >
                        {content ?? <span className="text-ink-3">—</span>}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {page && page.total > 0 ? (
        <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-ink-2">
          <span className="tabular-nums">
            {numberFormat.format(first)}–{numberFormat.format(last)} of {numberFormat.format(page.total)}
          </span>
          {onPageChange && pageCount > 1 ? (
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label="Previous page"
                disabled={page.index === 0}
                onClick={() => onPageChange(page.index - 1)}
                className="grid size-7 place-items-center rounded-md border border-line hover:bg-hover disabled:opacity-40"
              >
                <ChevronLeft className="size-3.5" aria-hidden />
              </button>
              <span className="px-1 tabular-nums">
                {page.index + 1} / {pageCount}
              </span>
              <button
                type="button"
                aria-label="Next page"
                disabled={page.index >= pageCount - 1}
                onClick={() => onPageChange(page.index + 1)}
                className="grid size-7 place-items-center rounded-md border border-line hover:bg-hover disabled:opacity-40"
              >
                <ChevronRight className="size-3.5" aria-hidden />
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
