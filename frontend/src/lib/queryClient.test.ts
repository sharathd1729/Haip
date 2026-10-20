import { describe, it, expect } from "vitest";
import { QueryClient, dehydrate } from "@tanstack/react-query";
import { shouldPersistQuery } from "./queryClient";

// The persisted cache must never carry live dashboard numbers: a restored "today" snapshot is yesterday's figures under the
// same key (the phone-shows-zeros report, 19 Oct 2026).
describe("shouldPersistQuery", () => {
  it("keeps ordinary queries and drops the dashboard ones", async () => {
    const qc = new QueryClient();
    qc.setQueryData(["bookable-properties"], [{ id: "p1" }]);
    qc.setQueryData(["business-overview", "t1", "2026-10-19", { date_preset: "today" }], { owner: {} });
    qc.setQueryData(["dashboard-overview", { date_preset: "today" }], {});
    qc.setQueryData(["work-queue", ""], { total: 3 });
    const keys = dehydrate(qc, { shouldDehydrateQuery: shouldPersistQuery }).queries.map(q => q.queryKey[0]);
    expect(keys).toEqual(["bookable-properties"]);
  });
});
