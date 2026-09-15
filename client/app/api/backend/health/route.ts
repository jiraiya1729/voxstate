// Next.js proxy route for FastAPI health checks.

import { backendUrl, proxyResponse } from "@/lib/backend";

export const dynamic = "force-dynamic";
export async function GET(): Promise<Response> {
  // Server-side proxy so the browser never needs the backend origin directly.
  try {
    return proxyResponse(await fetch(backendUrl("health"), { cache: "no-store" }));
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}
