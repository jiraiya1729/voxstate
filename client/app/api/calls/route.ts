import { backendUrl, proxyResponse } from "@/lib/backend";

export async function POST(request: Request): Promise<Response> {
  try {
    const response = await fetch(backendUrl("calls"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: await request.text(), cache: "no-store",
    });
    return proxyResponse(response);
  } catch {
    return Response.json({ detail: "The Voxstate backend is unavailable." }, { status: 503 });
  }
}
