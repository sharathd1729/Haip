interface Props { data: { campaigns: unknown[] } }

export function CampaignPerformanceWidget({ data }: Props) {
  if (!data.campaigns || data.campaigns.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-[11px] text-center px-4" style={{ color: "var(--haip-fg-subtle)" }}>
          Campaign data will appear after your first WhatsApp blast.
        </p>
      </div>
    );
  }
  return null;
}
