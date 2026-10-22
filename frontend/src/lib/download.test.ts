import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadErrorMessage, isIOSStandalone, saveBlob, toBlob, type DownloadWindow } from "./download";

function fakeWindow(nav: Partial<Navigator & { standalone?: boolean; canShare?: unknown; share?: unknown }>, standalone = false) {
  return {
    navigator: { userAgent: "Mozilla/5.0 (Windows NT 10.0)", platform: "Win32", maxTouchPoints: 0, ...nav },
    matchMedia: () => ({ matches: standalone }),
    URL: { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() },
    document,
    open: vi.fn(),
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
  } as unknown as DownloadWindow;
}

describe("saveBlob", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ""; });

  it("clicks a link that is in the document and revokes the URL only later", async () => {
    const win = fakeWindow({});
    let clickedWhileAttached = false;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clickedWhileAttached = document.body.contains(this);
      expect(this.download).toBe("r.csv");
    });
    expect(await saveBlob(new Blob(["a,b"], { type: "text/csv" }), "r.csv", win)).toBe("downloaded");
    expect(clickedWhileAttached).toBe(true);
    expect(document.querySelector("a")).toBeNull();                // removed again
    expect(win.URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10_000);
    expect(win.URL.revokeObjectURL).toHaveBeenCalledWith("blob:x");
    click.mockRestore();
  });

  it("hands the file to the share sheet in an installed iOS app", async () => {
    const share = vi.fn(async () => undefined);
    const win = fakeWindow({ userAgent: "iPhone", standalone: true, share, canShare: () => true } as never);
    expect(isIOSStandalone(win)).toBe(true);
    expect(await saveBlob(new Blob(["x"], { type: "text/csv" }), "r.csv", win)).toBe("shared");
    const files = (share.mock.calls[0] as unknown as [{ files: File[] }])[0].files;
    expect(files[0].name).toBe("r.csv");
  });

  it("opens the file in a new tab when an installed iOS app cannot share files", async () => {
    const win = fakeWindow({ userAgent: "iPhone" }, true);
    expect(await saveBlob(new Blob(["x"]), "r.xlsx", win)).toBe("opened");
    expect(win.open).toHaveBeenCalledWith("blob:x", "_blank", "noopener");
  });

  it("a person closing the share sheet is not an error", async () => {
    const share = vi.fn(async () => { throw Object.assign(new Error("x"), { name: "AbortError" }); });
    const win = fakeWindow({ userAgent: "iPhone", standalone: true, share, canShare: () => true } as never);
    expect(await saveBlob(new Blob(["x"]), "r.csv", win)).toBe("cancelled");
  });
});

describe("toBlob", () => {
  it("keeps the response's content type", () => {
    expect(toBlob("a,b", "text/csv").type).toBe("text/csv");
    const typed = new Blob(["x"], { type: "application/json" });
    expect(toBlob(typed, "application/json")).toBe(typed);
  });
});

describe("downloadErrorMessage", () => {
  it("reads the JSON detail out of a Blob error body", async () => {
    const data = new Blob([JSON.stringify({ detail: "Pick at most 31 days" })], { type: "application/json" });
    expect(await downloadErrorMessage({ response: { status: 422, data } })).toBe("Pick at most 31 days");
  });

  it("says a timeout plainly, and falls back when there is nothing to read", async () => {
    expect(await downloadErrorMessage({ code: "ECONNABORTED", message: "timeout of 120000ms exceeded" })).toMatch(/took too long/);
    expect(await downloadErrorMessage({ response: { status: 500, data: new Blob([""]) } }, "fallback")).toBe("fallback");
  });
});
