// Helpers for Next.js server routes that proxy browser requests to FastAPI.

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export function backendUrl(path: string): URL {
  // Build a FastAPI URL for server-side Next.js proxy routes.
  const baseUrl = process.env.VOXSTATE_BACKEND_URL ?? DEFAULT_BACKEND_URL;
  return new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
}

export async function proxyResponse(response: Response): Promise<Response> {
  // Preserve backend status/body while normalizing the content type for the UI.
  return new Response(await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}
