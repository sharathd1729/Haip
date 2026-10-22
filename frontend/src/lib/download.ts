// Saving a file the app made (report exports, the bookings CSV). One helper because the old inline code "did nothing" on
// several devices (22 Oct 2026): the Blob lost its content type, the <a> was never in the document (Firefox and some
// WebViews ignore a click on a detached link), the URL was revoked before the browser had read it, and an installed iOS
// app (standalone PWA) ignores `download` altogether. Errors from a `responseType: "blob"` request arrive as a Blob too,
// so their JSON detail was never shown.

/** Report exports can take a while on a big range: longer than the API client's global 20 s. */
export const DOWNLOAD_TIMEOUT_MS = 120_000;

/** How the file reached the person: saved by the browser, handed to the share sheet, or opened in a new tab. */
export type SaveResult = "downloaded" | "shared" | "opened" | "cancelled";

type Nav = Navigator & { standalone?: boolean; canShare?: (d: ShareData) => boolean };
/** The bits of `window` used here (a parameter so tests can pass a stand-in). */
export type DownloadWindow = Pick<Window, "navigator" | "matchMedia" | "document" | "open" | "setTimeout"> & { URL: typeof URL };
const realWindow = (): DownloadWindow => window as unknown as DownloadWindow;

function isIOS(nav: Nav): boolean {
  return /iPad|iPhone|iPod/.test(nav.userAgent) || (nav.platform === "MacIntel" && (nav.maxTouchPoints ?? 0) > 1);
}

/** An installed iOS web app, where `<a download>` does nothing. */
export function isIOSStandalone(win: DownloadWindow = realWindow()): boolean {
  const nav = win.navigator as Nav;
  if (nav.standalone === true) return true;
  return isIOS(nav) && !!win.matchMedia?.("(display-mode: standalone)").matches;
}

/** A Blob with the response's own content type (a bare `new Blob([data])` has none, which some browsers refuse to save). */
export function toBlob(data: BlobPart | Blob, contentType?: string | null): Blob {
  if (data instanceof Blob && (!contentType || data.type)) return data;
  return new Blob([data], { type: contentType || "application/octet-stream" });
}

export async function saveBlob(blob: Blob, filename: string, win: DownloadWindow = realWindow()): Promise<SaveResult> {
  const nav = win.navigator as Nav;
  if (isIOSStandalone(win)) {
    const file = typeof File !== "undefined" ? new File([blob], filename, { type: blob.type || "application/octet-stream" }) : null;
    if (file && typeof nav.share === "function" && nav.canShare?.({ files: [file] })) {
      try {
        await nav.share({ files: [file], title: filename });
        return "shared";
      } catch (e) {
        if ((e as { name?: string })?.name === "AbortError") return "cancelled";
        // any other failure: fall through and open it instead
      }
    }
    const url = win.URL.createObjectURL(blob);
    win.open(url, "_blank", "noopener");
    win.setTimeout(() => win.URL.revokeObjectURL(url), 60_000);
    return "opened";
  }
  const url = win.URL.createObjectURL(blob);
  const a = win.document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  a.style.display = "none";
  win.document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking at once can cancel the save before the browser has read the file.
  win.setTimeout(() => win.URL.revokeObjectURL(url), 10_000);
  return "downloaded";
}

// Older WebViews (and jsdom) have no Blob.text().
function blobText(b: Blob): Promise<string> {
  if (typeof b.text === "function") return b.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error);
    r.readAsText(b);
  });
}

/** The real reason a download request failed. A blob request's error body is a Blob: read it as text, then JSON `detail`. */
export async function downloadErrorMessage(err: unknown, fallback = "The download failed. Please try again."): Promise<string> {
  const e = err as { code?: string; message?: string; response?: { status?: number; data?: unknown } };
  if (e?.code === "ECONNABORTED" || /timeout/i.test(e?.message ?? "")) {
    return "The export took too long. Try a shorter date range, or fewer columns.";
  }
  let data: unknown = e?.response?.data;
  if (data instanceof Blob) {
    try { data = await blobText(data); } catch { data = undefined; }
  }
  if (typeof data === "string") {
    const text = data.trim();
    if (!text) return fallback;
    try { data = JSON.parse(text); } catch { return text.slice(0, 300); }
  }
  const detail = (data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(d => (d as { msg?: string })?.msg ?? JSON.stringify(d)).join("; ");
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  if (e?.response?.status === 403) return "You don't have access to this export.";
  return fallback;
}
