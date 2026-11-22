import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Filters } from "../src/api/data";
import ExportControl, {
  EXPORT_DISABLED_TIP,
  EXPORT_FAILED,
  EXPORT_READY,
} from "../src/components/ExportControl";

const FILTERS: Filters = {
  variable: "temperature_c",
  resolution: "day",
  start: "2026-01-18",
  end: "2026-02-16",
  landUses: ["Parkland"],
  sensorIds: [2],
  excludeFlagged: true,
};
const LARGE = "This export contains a large amount of data and may take a moment to prepare.";

let replies: Response[];
let bodies: Record<string, unknown>[];
let clicked: string[];

const file = (name: string) =>
  new Response("a,b\r\n1,2\r\n", {
    status: 200,
    headers: { "Content-Disposition": `attachment; filename="${name}"`, "X-Export-Rows": "1" },
  });
const failure = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ error: { code, message } }), { status });

beforeEach(() => {
  replies = [];
  bodies = [];
  clicked = [];
  document.cookie = "mem_csrf=test-csrf; path=/";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("test-csrf");
      return replies.shift() ?? failure(500, "internal_error", "boom");
    }),
  );
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this.download);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function openDialog() {
  render(<ExportControl filters={FILTERS} applied />);
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  return screen.getByRole("dialog", { name: "Export data" });
}

describe("export button", () => {
  it("is disabled with the UC3 tooltip until a filter is applied", async () => {
    render(<ExportControl filters={FILTERS} applied={false} />);
    const button = screen.getByRole("button", { name: "Export" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(EXPORT_DISABLED_TIP);
    await userEvent.hover(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent(EXPORT_DISABLED_TIP);
    await userEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("opens the format dialog once a filter is applied, and Escape closes it", async () => {
    const dialog = await openDialog();
    expect(screen.getByRole("radio", { name: /CSV/ })).toHaveFocus();
    expect(screen.getByRole("radio", { name: /PDF report/ })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(dialog).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toHaveFocus();
  });
});

describe("export flow", () => {
  it("sends the applied filters, saves the file and says it is ready", async () => {
    replies.push(file("maribyrnong_temperature_c_day_2026-01-18_2026-02-16.pdf"));
    await openDialog();
    await userEvent.click(screen.getByRole("radio", { name: /PDF report/ }));
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(screen.getByText(EXPORT_READY)).toBeInTheDocument());
    expect(bodies[0]).toEqual({
      format: "pdf",
      variable: "temperature_c",
      resolution: "day",
      start: "2026-01-18",
      end: "2026-02-16",
      land_use: ["Parkland"],
      sensor_ids: [2],
      exclude_flagged: true,
      confirm_large: false,
    });
    expect(clicked).toEqual(["maribyrnong_temperature_c_day_2026-01-18_2026-02-16.pdf"]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("warns about a large export and continues only after confirmation", async () => {
    replies.push(failure(409, "large_export", LARGE), file("big.csv"));
    await openDialog();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(LARGE);
    expect(clicked).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(clicked).toEqual(["big.csv"]));
    expect(bodies.map((b) => b.confirm_large)).toEqual([false, true]);
  });

  it("cancelling the large-export warning downloads nothing", async () => {
    replies.push(failure(409, "large_export", LARGE));
    await openDialog();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(clicked).toEqual([]);
  });

  it("shows the UC3 failure message for server errors and lost connections", async () => {
    replies.push(failure(500, "export_failed", "anything"));
    await openDialog();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(EXPORT_FAILED);
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("alert")).toHaveTextContent(EXPORT_FAILED);
    expect(screen.queryByText(EXPORT_READY)).not.toBeInTheDocument();
  });

  it("shows the server's explanation when the filters need changing", async () => {
    replies.push(failure(404, "no_data", "No data available for the selected filters."));
    await openDialog();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No data available for the selected filters.",
    );
  });
});
