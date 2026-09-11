import { backendUrl, proxyResponse } from "@/lib/backend";

export const dynamic = "force-dynamic";
export async function GET(): Promise<Response> {
  try {
    return proxyResponse(await fetch(backendUrl("health"), { cache: "no-store" }));
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}
