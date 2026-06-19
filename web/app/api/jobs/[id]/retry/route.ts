import { NextResponse } from "next/server";

const PY = process.env.PY_BACKEND ?? "http://127.0.0.1:8765";

export async function POST(_req: Request, { params }: { params: { id: string } }) {
  const r = await fetch(`${PY}/api/jobs/${params.id}/retry`, { method: "POST" });
  return new NextResponse(r.body, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
  });
}
