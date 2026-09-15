// Next.js proxy route for loading enabled agent choices from FastAPI.

import { backendUrl, proxyResponse } from "@/lib/backend";

export async function GET(): Promise<Response> {
  // Server-side proxy for the operator console's enabled-agent list.
  try {
    const response = await fetch(backendUrl("agents"), { cache: "no-store" });
    return proxyResponse(response);
  } catch {
    return Response.json({ detail: "The Voxstate backend is unavailable." }, { status: 503 });
  }
}
