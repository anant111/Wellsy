import { NextResponse } from "next/server";

const PY = process.env.PY_BACKEND ?? "http://127.0.0.1:8765";

export async function GET() {
  const r = await fetch(`${PY}/api/jobs`, { cache: "no-store" });
  return new NextResponse(r.body, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
  });
}

export async function POST(req: Request) {
  const body = await req.text();
  const r = await fetch(`${PY}/api/jobs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
  return new NextResponse(r.body, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
  });
}
