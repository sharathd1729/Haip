"use client";
// The three-pane builder (Puck, MIT): sections on the left, the page in the middle, fields on the right. Puck edits
// one page's content array; HAIP keeps the document, validation, autosave and approvals. Fields and sections come from
// the same spec and components as everything else, so what's built here is exactly what guests see.
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { Puck, type Config, type Data, type Field } from "@puckeditor/core";
import "@puckeditor/core/puck.css";
import { pack, packVars } from "@/site-blocks/packs";
import { SECTIONS } from "@/site-blocks/sections";
import { SPEC, type FieldSpec, type LiveData, type Page, type SiteEnv } from "@/site-blocks/types";
import type { MediaItem } from "@/lib/website";
import { PhotoThumb } from "./FieldPanel";

const LAYOUT_LABEL: Record<string, string> = { split: "Split", full: "Full photo", centred: "Centred", cards: "Cards", list: "List",
  image_left: "Photo left", image_right: "Photo right", grid: "Grid", single: "Single", mosaic: "Mosaic", left: "Left" };

function opts(f: FieldSpec) {
  const list = f.options || ((SPEC as unknown as Record<string, string[]>)[f.options_from || ""] || []);
  return list.map(o => ({ label: o === "all" ? "All" : o[0].toUpperCase() + o.slice(1), value: o }));
}

function toPuck(f: FieldSpec, media: MediaItem[], pickPhoto: (cb: (ref: string) => void) => void): Field {
  switch (f.kind) {
    case "text": case "link": case "date": return { type: "text", label: f.label };
    case "textarea": return { type: "textarea", label: f.label };
    case "select": return { type: "select", label: f.label, options: opts(f) };
    case "toggle": return { type: "radio", label: f.label, options: [{ label: "Yes", value: true }, { label: "No", value: false }] };
    case "lines": return { type: "custom", label: f.label, render: ({ value, onChange }) => (
      <textarea className="w-full rounded-md border p-2 text-sm" rows={4} value={(Array.isArray(value) ? value : []).join("\n")}
        onChange={e => onChange(e.target.value.split("\n").slice(0, f.max_items || 10))} />) };
    case "tags": return { type: "custom", label: f.label, render: ({ value, onChange }) => {
      const set: string[] = Array.isArray(value) ? value : [];
      return <div className="flex flex-wrap gap-1">{opts(f).map(o => { const on = set.includes(o.value); return (
        <button key={o.value} type="button" aria-pressed={on} onClick={() => onChange(on ? set.filter(x => x !== o.value) : [...set, o.value])}
          className={`rounded-full border px-2 py-1 text-xs ${on ? "bg-primary text-primary-foreground" : ""}`}>{o.value}</button>); })}</div>;
    } };
    case "image": return { type: "custom", label: f.label, render: ({ value, onChange }) => (
      <PhotoThumb refValue={typeof value === "string" ? value : ""} media={media} onPick={() => pickPhoto(r => onChange(r))} onClear={() => onChange("")} />) };
    case "images": return { type: "custom", label: f.label, render: ({ value, onChange }) => {
      const list: string[] = Array.isArray(value) ? value : [];
      return <div className="grid gap-1.5"><span className="text-xs">{list.length} photo{list.length === 1 ? "" : "s"}</span>
        <button type="button" className="rounded-md border px-2 py-1 text-xs" onClick={() => pickPhoto(r => onChange(list.includes(r) ? list : [...list, r]))}>Add photo</button>
        {list.length > 0 && <button type="button" className="rounded-md border px-2 py-1 text-xs" onClick={() => onChange(list.slice(0, -1))}>Remove last</button>}</div>;
    } };
    case "list": return { type: "array", label: f.label, max: f.max_items,
      arrayFields: Object.fromEntries((f.item || []).map(s => [s.key, toPuck(s, media, pickPhoto)])),
      defaultItemProps: Object.fromEntries((f.item || []).map(s => [s.key, s.kind === "select" ? opts(s)[0]?.value ?? "" : ""])),
      getItemSummary: (item: Record<string, unknown>) => String(item.q || item.name || item.place || "Item") };
  }
}

export function PuckBuilder({ page, live, env, media, pickPhoto, onChange }: {
  page: Page; live: LiveData; env: SiteEnv; media: MediaItem[]; pickPhoto: (cb: (ref: string) => void) => void;
  onChange: (content: Page["content"]) => void;
}) {
  const config = useMemo<Config>(() => {
    const components: Config["components"] = {};
    for (const [type, spec] of Object.entries(SPEC.blocks)) {
      const fields: Record<string, Field> = {};
      if (spec.layouts && spec.layouts.length > 1) fields.layout = { type: "radio", label: "Layout", options: spec.layouts.map(l => ({ label: LAYOUT_LABEL[l] || l, value: l })) };
      fields.background = { type: "radio", label: "Background", options: SPEC.backgrounds.map(b => ({ label: b === "page" ? "Page" : b === "soft" ? "Soft" : "Brand", value: b })) };
      for (const f of spec.fields) fields[f.key] = toPuck(f, media, pickPhoto);
      components[type] = {
        label: spec.label, fields,
        defaultProps: { layout: spec.layouts?.[0] || "", background: "page" },
        permissions: spec.system ? { delete: false, duplicate: false, drag: false, insert: false } : undefined,
        render: (props: Record<string, unknown>) => {
          const node = SECTIONS[type]?.({ ...(props as Record<string, unknown>), id: String(props.id) } as never, { env, live }) ?? null;
          const bg = props.background && props.background !== "page" ? `bg-${props.background}` : "";
          return <section className={bg}>{node as ReactNode}</section>;
        },
      };
    }
    const system = Object.entries(SPEC.blocks).filter(([, s]) => s.system).map(([k]) => k);
    return {
      components,
      categories: {
        content: { title: "Sections", components: Object.keys(SPEC.blocks).filter(k => !system.includes(k)) },
        system: { title: "Built by HAIP", components: system, visible: false },
      },
      root: {
        fields: {},                 // page name and SEO live in HAIP's Page panel, not here
        render: ({ children }: { children?: ReactNode }) => (
          <div className={`hs p-${live.doc.theme.personality} in-editor`} style={packVars(pack(live.doc.theme.pack)) as CSSProperties}>{children}</div>
        ),
      },
    };
  }, [env, live, media, pickPhoto]);

  const data = useMemo<Data>(() => ({ root: { props: {} }, content: page.content.map(b => ({ type: b.type, props: b.props })) }), [page.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="h-full min-h-0">
      <Puck config={config} data={data} height="100%" headerTitle={page.title}
        viewports={[{ width: 390, height: "auto", label: "Phone" }, { width: 768, height: "auto", label: "Tablet" }, { width: 1200, height: "auto", label: "Desktop" }]}
        onChange={(d: Data) => onChange(d.content.map(c => ({ type: String(c.type), props: { ...(c.props as Record<string, unknown>), id: String((c.props as { id?: string }).id) } })))}
        overrides={{ headerActions: () => <></> }} />
    </div>
  );
}
