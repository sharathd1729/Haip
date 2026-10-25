"use client";
// The editor's working copy of the site document. Edits apply locally at once, autosave 1.2 s later against the sha
// the editor last saw (a stale editor gets a conflict, never overwrites), and undo/redo keep the last 60 snapshots.
import { useCallback, useEffect, useRef, useState } from "react";
import { errorCode, webApi, webError, type Check, type DraftOut } from "@/lib/website";
import type { SiteDoc } from "@/site-blocks/types";

export type SaveState = "idle" | "saving" | "saved" | "conflict" | "error";

export function useDraft() {
  const [doc, setDoc] = useState<SiteDoc | null>(null);
  const [version, setVersion] = useState<DraftOut["version"] | null>(null);
  const [checks, setChecks] = useState<Check[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState<unknown>(null);
  const base = useRef<string>("");
  const rev = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const past = useRef<SiteDoc[]>([]);
  const future = useRef<SiteDoc[]>([]);
  const latest = useRef<SiteDoc | null>(null);
  const [, force] = useState(0);

  const adopt = useCallback((d: DraftOut, keepLocal = false) => {
    base.current = d.version.sha256;
    setVersion(d.version);
    setChecks(d.checks);
    setProblems(d.problems);
    if (!keepLocal) { latest.current = d.doc; setDoc(d.doc); }
  }, []);

  const load = useCallback(async () => {
    try {
      setLoadError(null);
      const d = await webApi.draft();
      past.current = []; future.current = [];
      adopt(d);
      setState("idle");
    } catch (e) { setLoadError(e); }
  }, [adopt]);

  useEffect(() => { load(); }, [load]);

  /** Saves now. Resolves to null when saved, else the error (the screen can show the server's problems and undo). */
  const flush = useCallback(async (): Promise<unknown> => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    const current = latest.current;
    if (!current || !base.current) return null;
    const myRev = rev.current;
    setState("saving");
    try {
      const d = await webApi.save(current, base.current);
      // Keep what the user typed meanwhile; adopt the server's cleaned copy only when nothing changed since.
      adopt(d, rev.current !== myRev);
      setState("saved");
      setError("");
      return null;
    } catch (e) {
      if (errorCode(e) === "version_changed") setState("conflict");
      else { setState("error"); setError(webError(e, "Couldn't save. Your changes are kept here; we'll retry.")); }
      return e;
    }
  }, [adopt]);

  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, 1200);
  }, [flush]);

  const update = useCallback((fn: (d: SiteDoc) => void) => {
    const cur = latest.current;
    if (!cur) return;
    const next = structuredClone(cur);
    fn(next);
    past.current = [...past.current.slice(-59), cur];
    future.current = [];
    latest.current = next;
    rev.current += 1;
    setDoc(next);
    setState("saving");
    schedule();
  }, [schedule]);

  const replace = useCallback((next: SiteDoc) => update(d => { Object.assign(d, structuredClone(next)); }), [update]);

  const undo = useCallback(() => {
    const prev = past.current.pop();
    if (!prev || !latest.current) return;
    future.current = [latest.current, ...future.current];
    latest.current = prev; rev.current += 1; setDoc(prev); schedule(); force(x => x + 1);
  }, [schedule]);

  const redo = useCallback(() => {
    const [nxt, ...rest] = future.current;
    if (!nxt || !latest.current) return;
    past.current = [...past.current, latest.current];
    future.current = rest;
    latest.current = nxt; rev.current += 1; setDoc(nxt); schedule(); force(x => x + 1);
  }, [schedule]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (timer.current) { e.preventDefault(); } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  return {
    doc, version, checks, problems, state, error, loadError, load, update, replace, flush, undo, redo,
    canUndo: past.current.length > 0, canRedo: future.current.length > 0, adopt,
  };
}

export type Draft = ReturnType<typeof useDraft>;
