import { NextResponse } from "next/server";

const PY = process.env.PY_BACKEND ?? "http://127.0.0.1:8765";

export async function GET(req: Request, { params }: { params: { jobId: string; path: string[] } }) {
  const target = `${PY}/api/media/${params.jobId}/${params.path.join("/")}`;
  const r = await fetch(target, {
    cache: "no-store",
    // Preserve range requests for video streaming
    headers: req.headers.get("range") ? { range: req.headers.get("range")! } : {},
  });
  // Pass through body + relevant headers
  const headers = new Headers();
  const ct = r.headers.get("content-type");
  const cl = r.headers.get("content-length");
  const ar = r.headers.get("accept-ranges");
  const cr = r.headers.get("content-range");
  if (ct) headers.set("content-type", ct);
  if (cl) headers.set("content-length", cl);
  if (ar) headers.set("accept-ranges", ar);
  if (cr) headers.set("content-range", cr);
  return new NextResponse(r.body, { status: r.status, headers });
}
