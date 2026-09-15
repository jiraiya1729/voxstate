// Shared TypeScript response types used by the operator console and proxy routes.

export type HealthResponse = { status: "ok" };
export type AgentResponse = { id: string; name: string; enabled: boolean };
export type CallResponse = { id: string; status: string; provider_call_id: string; agent_id?: string | null };
