import { NextRequest, NextResponse } from "next/server";

const RW_URL   = (process.env.RENTALWISE_URL   || "").replace(/\/$/, "");
const RW_TOKEN = process.env.RENTALWISE_TOKEN  || "";

export async function POST(req: NextRequest) {
  if (!RW_URL) {
    return NextResponse.json({ error: "RENTALWISE_URL not configured" }, { status: 503 });
  }

  try {
    const body = await req.json().catch(() => ({}));
    const res  = await fetch(`${RW_URL}/rest/thread/query`, {
      method:  "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${RW_TOKEN}`,
        "Accept":        "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[rentalwise/threads]", err);
    return NextResponse.json({ error: "Failed to reach RentalWise" }, { status: 502 });
  }
}
