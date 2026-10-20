// Small helpers shared by the interactive site pieces.
export async function readError(r: Response, fallback: string): Promise<string> {
  try {
    const j = await r.json();
    return j?.detail?.message || fallback;
  } catch {
    return fallback;
  }
}
