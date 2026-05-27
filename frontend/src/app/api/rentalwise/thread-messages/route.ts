import { NextRequest, NextResponse } from "next/server";
import { getRWCredentials } from "../_helpers";

export async function POST(req: NextRequest) {
  try {
    const { rwUrl, rwAuth } = await getRWCredentials(req.headers.get("Authorization"));
    const body = await req.json().catch(() => ({}));

    const res = await fetch(`${rwUrl}/rest/thread-message/query`, {
      method:  "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": rwAuth,
        "Accept":        "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    console.error("[rentalwise/thread-messages]", err);
    const is503 = err.message?.includes("not connected") ||
                  err.message?.includes("not configured") ||
                  err.message?.includes("credentials missing") ||
                  err.message?.includes("not authenticated");
    return NextResponse.json({ error: err.message ?? "Failed to reach RentalWise" }, { status: is503 ? 503 : 502 });
  }
}
