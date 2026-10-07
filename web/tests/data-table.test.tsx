import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { applyLocalQuery, DataTable, nextSort, useLocalTable, type Column } from "@/components/ui";

interface Video {
  id: string;
  name: string;
  fps: number | null;
}

const COLUMNS: Column<Video>[] = [
  { key: "name", header: "Name", sortable: true },
  { key: "fps", header: "FPS", sortable: true, align: "right" },
];

const ROWS: Video[] = [
  { id: "a", name: "kitchen_02.mp4", fps: 30 },
  { id: "b", name: "bench_10.mov", fps: 60 },
  { id: "c", name: "bench_9.mov", fps: null },
];

describe("nextSort", () => {
  it("starts ascending and toggles on the same column", () => {
    expect(nextSort(null, "name")).toEqual({ key: "name", dir: "asc" });
    expect(nextSort({ key: "name", dir: "asc" }, "name")).toEqual({ key: "name", dir: "desc" });
    expect(nextSort({ key: "name", dir: "desc" }, "name")).toEqual({ key: "name", dir: "asc" });
    expect(nextSort({ key: "name", dir: "desc" }, "fps")).toEqual({ key: "fps", dir: "asc" });
  });
});

describe("applyLocalQuery", () => {
  it("sorts strings naturally and keeps nulls last", () => {
    const asc = applyLocalQuery(ROWS, COLUMNS, { sort: { key: "name", dir: "asc" } }).map((r) => r.id);
    expect(asc).toEqual(["c", "b", "a"]); // bench_9 < bench_10 < kitchen_02
    const fpsDesc = applyLocalQuery(ROWS, COLUMNS, { sort: { key: "fps", dir: "desc" } }).map((r) => r.id);
    expect(fpsDesc).toEqual(["b", "a", "c"]);
  });

  it("filters across columns, case-insensitively", () => {
    expect(applyLocalQuery(ROWS, COLUMNS, { filter: "BENCH" }).map((r) => r.id)).toEqual(["b", "c"]);
    expect(applyLocalQuery(ROWS, COLUMNS, { filter: "60" }).map((r) => r.id)).toEqual(["b"]);
  });
});

describe("DataTable (controlled)", () => {
  it("reports sort changes instead of sorting itself", async () => {
    const onSortChange = vi.fn();
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} sort={null} onSortChange={onSortChange} />);
    await userEvent.click(screen.getByRole("button", { name: /name/i }));
    expect(onSortChange).toHaveBeenCalledWith({ key: "name", dir: "asc" });
    // rows keep the order they were given
    const cells = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(cells).toEqual(["kitchen_02.mp4", "bench_10.mov", "bench_9.mov"]);
  });

  it("marks the sorted column for assistive tech", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} sort={{ key: "fps", dir: "desc" }} onSortChange={() => {}} />);
    expect(screen.getByRole("columnheader", { name: /fps/i })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: /name/i })).toHaveAttribute("aria-sort", "none");
  });

  it("renders the empty state and a dash for missing values", () => {
    const { rerender } = render(<DataTable columns={COLUMNS} rows={[]} rowKey={(r) => r.id} />);
    expect(screen.getByRole("status")).toHaveTextContent("No data yet");
    rerender(<DataTable columns={COLUMNS} rows={[ROWS[2]]} rowKey={(r) => r.id} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows server-side paging and requests the next page", async () => {
    const onPageChange = vi.fn();
    render(
      <DataTable
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        page={{ index: 0, size: 3, total: 1200 }}
        onPageChange={onPageChange}
      />,
    );
    expect(screen.getByText("1–3 of 1,200")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });
});

function LocalTable() {
  const table = useLocalTable(ROWS, COLUMNS, 2);
  return <DataTable {...table} columns={COLUMNS} rowKey={(r) => r.id} filterPlaceholder="Filter videos" />;
}

describe("useLocalTable", () => {
  it("wires filter, sort, and paging together", async () => {
    render(<LocalTable />);
    expect(screen.getByText("1–2 of 3")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox", { name: "Filter videos" }), "bench");
    expect(screen.getByText("1–2 of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /name/i }));
    const first = within(screen.getAllByRole("row")[1]).getAllByRole("cell")[0];
    expect(first).toHaveTextContent("bench_9.mov");
    await userEvent.clear(screen.getByRole("searchbox"));
    await userEvent.type(screen.getByRole("searchbox"), "nothing-matches");
    expect(screen.getByRole("status")).toHaveTextContent("No rows match this filter");
  });
});
