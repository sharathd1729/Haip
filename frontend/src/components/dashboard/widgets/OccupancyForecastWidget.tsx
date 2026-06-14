interface Props { data: { upcoming_stays: number; property_count: number } }

export function OccupancyForecastWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-2">
      <p className="text-3xl font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>
        {data.upcoming_stays}
      </p>
      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
        stays booked in next 30 days
      </p>
      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
        across {data.property_count} {data.property_count === 1 ? "property" : "properties"}
      </p>
    </div>
  );
}
