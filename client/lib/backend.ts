const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export function backendUrl(path: string): URL {
  const baseUrl = process.env.VOXSTATE_BACKEND_URL ?? DEFAULT_BACKEND_URL;
  return new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
}

export async function proxyResponse(response: Response): Promise<Response> {
  return new Response(await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}
