"use client";
// Website W6: "Get your website ready" at the top of the Website page. Each step is read from the draft and the site
// (nothing new is stored); a step's button opens the sheet that does it. Hidden once every step is done.
import { Check } from "lucide-react";
import { Card, CardBody } from "@/components/ui/kit";
import type { SiteOut } from "@/lib/website";
import type { SpecV2 } from "@/site-blocks/v2/types";

export type SetupAction = "logo" | "contact" | "menu" | "publish" | "domain" | "design";

export function setupSteps(doc: SpecV2, site: SiteOut, hasStays: boolean): { key: SetupAction; title: string; done: boolean; hint: string }[] {
  const c = doc.site.contact;
  const own = site.domains.find(d => d.kind === "custom" && d.status !== "removed");
  return [
    { key: "logo", title: "Add your logo", done: !!doc.site.brand?.logo, hint: "Shown at the top of every page and in the browser tab." },
    { key: "contact", title: "Your phone and WhatsApp", done: !!(c.whatsapp || c.phone), hint: "Every WhatsApp button opens a chat with this number." },
    { key: "menu", title: "Check the menu and footer", done: !!doc.site.menus, hint: "Choose the links guests see at the top and bottom." },
    ...(hasStays ? [{ key: "design" as const, title: "Design your stay pages", done: !!doc.templates?.stay, hint: "One design gives every stay its own page." }] : []),
    { key: "publish", title: "Publish your website", done: !!site.live, hint: "Nobody sees it until you publish." },
    { key: "domain", title: "Connect your own domain", done: own?.status === "active", hint: own ? `${own.hostname}: waiting for DNS` : "Like www.yourstay.in. Optional." },
  ];
}

export function SetupChecklist({ doc, site, hasStays, canEdit, onAction }: {
  doc: SpecV2; site: SiteOut; hasStays: boolean; canEdit: boolean; onAction: (a: SetupAction) => void;
}) {
  const steps = setupSteps(doc, site, hasStays);
  const done = steps.filter(s => s.done).length;
  if (done === steps.length) return null;
  return (
    <Card>
      <CardBody className="grid gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="font-semibold">Get your website ready</p>
          <span className="text-sm text-[var(--haip-fg-muted)]">{done} of {steps.length} done</span>
        </div>
        <ol className="grid gap-1">
          {steps.map(s => (
            <li key={s.key} className="flex min-h-12 items-center gap-3 border-t border-[var(--haip-border)] pt-2 first:border-0 first:pt-0">
              <span aria-hidden="true" className={`grid h-6 w-6 shrink-0 place-items-center rounded-full ${s.done ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "border-2 border-[var(--haip-border)]"}`}>
                {s.done && <Check size={14} />}</span>
              <span className="min-w-0 flex-1"><b className={`block text-sm font-semibold ${s.done ? "text-[var(--haip-fg-muted)] line-through decoration-1" : ""}`}>{s.title}</b>
                {!s.done && <span className="block text-xs text-[var(--haip-fg-muted)]">{s.hint}</span>}</span>
              {!s.done && canEdit && <button type="button" className="min-h-11 shrink-0 px-2 text-sm font-semibold text-[var(--primary)]" onClick={() => onAction(s.key)}>Do it</button>}
              <span className="sr-only">{s.done ? "Done" : "Not done yet"}</span>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}
