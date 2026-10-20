import { StatusPill, type Tone } from "@/components/ui/page";

/** Where a knowledge entry came from. Mirrors backend knowledge_freshness.SOURCE_LABELS (short form for a badge). */
const SOURCES: Record<string, { label: string; tone: Tone }> = {
  manual: { label: "Owner", tone: "brand" },
  instagram: { label: "Instagram", tone: "highlight" },
  meta_ad: { label: "Ad", tone: "info" },
  website: { label: "Website", tone: "neutral" },
  upload: { label: "Document", tone: "neutral" },
  document: { label: "Document", tone: "neutral" },
  conversation: { label: "Conversation", tone: "neutral" },
  owner_notes: { label: "Imported notes", tone: "neutral" },
};

export function sourceLabel(source: string): string {
  return SOURCES[source]?.label ?? source.replace(/_/g, " ");
}

export function SourceBadge({ source }: { source: string }) {
  const s = SOURCES[source] ?? { label: sourceLabel(source), tone: "neutral" as Tone };
  return <StatusPill tone={s.tone}>{s.label}</StatusPill>;
}

/** Review flags set by the server on social content. A quoted price is never used as a price. */
export function FlagBadges({ flags }: { flags?: string[] | null }) {
  if (!flags?.length) return null;
  return (
    <>
      {flags.includes("mentions_price") && <StatusPill tone="warning">Quotes a price (not used as a price)</StatusPill>}
      {flags.includes("mentions_offer") && <StatusPill tone="info">Mentions an offer</StatusPill>}
    </>
  );
}
