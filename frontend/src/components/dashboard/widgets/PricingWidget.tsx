interface Props { data: { note?: string } }

export function PricingWidget({ data }: Props) {
  return (
    <div className="flex items-center justify-center h-full">
      <p className="text-[11px] text-center px-4" style={{ color: "var(--haip-fg-subtle)" }}>
        {data.note ?? "Pricing signals require rate plan data."}
      </p>
    </div>
  );
}
