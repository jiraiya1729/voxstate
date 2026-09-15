"use client";

// Thin operator console for checking readiness, selecting an agent, and starting calls.

import { AlertCircle, ArrowUpRight, Check, Clock3, LoaderCircle, Phone, PhoneCall, RefreshCw, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import type { AgentResponse, CallResponse, HealthResponse } from "@/lib/api";

type RequestState = "idle" | "submitting" | "success" | "error";
type HealthState = "checking" | "online" | "offline";
const E164_PATTERN = /^\+[1-9]\d{7,14}$/;

export default function Home() {
  // Thin operator console: load health/agents, validate a number, and start a call.
  const [destination, setDestination] = useState("");
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [health, setHealth] = useState<HealthState>("checking");
  const [call, setCall] = useState<CallResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentResponse[]>([]);
  const [agentId, setAgentId] = useState("");

  async function checkHealth() {
    // Manual refresh path for the backend readiness pill.
    setHealth("checking");
    setHealth(await fetchHealth());
  }

  useEffect(() => {
    let cancelled = false;

    void fetchHealth().then((nextHealth) => {
      if (!cancelled) setHealth(nextHealth);
    });
    void fetchAgents().then((availableAgents) => {
      if (!cancelled) {
        setAgents(availableAgents);
        setAgentId(availableAgents[0]?.id ?? "");
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  async function initiateCall(event: FormEvent<HTMLFormElement>) {
    // Validate E.164 input, call the Next.js proxy, and display backend feedback.
    event.preventDefault();
    const normalized = destination.trim().replaceAll(" ", "");
    setCall(null);
    setError(null);
    if (!E164_PATTERN.test(normalized)) {
      setRequestState("error");
      setError("Use the full number with country code, for example +1 415 555 2671.");
      return;
    }
    setRequestState("submitting");
    try {
      const response = await fetch("/api/calls", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: normalized, agent_id: agentId || undefined }),
      });
      const body = (await response.json()) as CallResponse | { detail?: unknown };
      if (!response.ok) {
        const message = "detail" in body ? formatError(body.detail) : "The call could not be started.";
        throw new Error(message);
      }
      setCall(body as CallResponse);
      setRequestState("success");
    } catch (caught) {
      setRequestState("error");
      setError(caught instanceof Error ? caught.message : "The call could not be started.");
    }
  }

  const isSubmitting = requestState === "submitting";
  const isReady = health === "online";

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Voxstate home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span>Voxstate</span>
        </a>
        <button className="availability" type="button" onClick={checkHealth} aria-label="Check service status">
          <span className={`status-dot status-${health}`} />
          <span>{isReady ? "Ready to call" : health === "offline" ? "Unavailable" : "Connecting"}</span>
          <RefreshCw size={14} className={health === "checking" ? "spin" : ""} />
        </button>
      </header>

      <section className="workspace" id="top">
        <div className="call-area">
          <p className="eyebrow">Outbound calling</p>
          <h1>Who would you like to call?</h1>
          <p className="intro">Enter a phone number and Voxstate will start the conversation for you.</p>

          <form className="call-form" onSubmit={initiateCall}>
            <label htmlFor="agent">Agent</label>
            <select
              id="agent"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
              disabled={isSubmitting || agents.length === 0}
            >
              {agents.length === 0 ? <option value="">No enabled agents</option> : null}
              {agents.filter((agent) => agent.enabled).map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name}</option>
              ))}
            </select>
            <label htmlFor="destination">Phone number</label>
            <div className="number-input">
              <span className="input-icon"><Phone size={19} aria-hidden="true" /></span>
              <input id="destination" name="destination" type="tel" inputMode="tel" autoComplete="tel"
                placeholder="+1 415 555 2671" value={destination}
                onChange={(event) => setDestination(event.target.value)}
                aria-describedby="number-hint" disabled={isSubmitting} />
              <span className="format-label">INTL</span>
            </div>
            <div className="form-meta">
              <p id="number-hint">Include the country code</p>
              <span><ShieldCheck size={14} /> Secure connection</span>
            </div>
            <button className="call-button" type="submit" disabled={isSubmitting || !isReady || !agentId}>
              {isSubmitting ? <LoaderCircle className="spin" size={19} /> : <PhoneCall size={19} />}
              {isSubmitting ? "Starting call..." : "Start call"}
            </button>
          </form>

          <div className="result-region" aria-live="polite">
            {requestState === "idle" && <div className="idle-note"><Clock3 size={16} /><span>Your call status will appear here.</span></div>}
            {requestState === "submitting" && <div className="notice neutral"><LoaderCircle className="spin" size={19} /><div><strong>Connecting your call</strong><span>This usually takes a few seconds.</span></div></div>}
            {requestState === "success" && call && (
              <div className="notice success">
                <span className="notice-icon"><Check size={18} /></span>
                <div><strong>Call started</strong><span>We&apos;re calling {destination} now.</span></div>
                <span className="call-status">{call.status}</span>
              </div>
            )}
            {requestState === "error" && error && <div className="notice error"><AlertCircle size={19} /><div><strong>Call not started</strong><span>{error}</span></div></div>}
          </div>
        </div>

        <aside className="activity-panel">
          <div className="activity-top">
            <span className="phone-orbit"><PhoneCall size={28} /></span>
            <p>Calls made with Voxstate</p>
            <strong>Natural conversations,<br />started in one click.</strong>
          </div>
          <div className="activity-bottom">
            <div><p className="eyebrow">Today</p><h2>Recent calls</h2></div>
            {call ? (
              <div className="recent-call">
                <span className="recent-icon"><Phone size={17} /></span>
                <div><strong>{destination}</strong><small>Just now · {call.status}</small></div>
                <ArrowUpRight size={17} />
              </div>
            ) : <div className="no-calls"><span>0</span><p>No calls yet today</p></div>}
          </div>
        </aside>
      </section>
      <footer className="footer"><span>Voxstate</span><span>Voice conversations, on demand.</span></footer>
    </main>
  );
}

async function fetchHealth(): Promise<HealthState> {
  // Convert the backend health contract into the UI's small state machine.
  try {
    const response = await fetch("/api/backend/health", { cache: "no-store" });
    const body = (await response.json()) as HealthResponse;
    return response.ok && body.status === "ok" ? "online" : "offline";
  } catch {
    return "offline";
  }
}

function formatError(detail: unknown): string {
  // Convert FastAPI error details into a short operator-facing message.
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = String(detail.code).replaceAll("_", " ");
    return code.charAt(0).toUpperCase() + code.slice(1);
  }
  return "The call could not be started. Please try again.";
}

async function fetchAgents(): Promise<AgentResponse[]> {
  // Load selectable agents; failures render as an empty disabled selector.
  try {
    const response = await fetch("/api/agents", { cache: "no-store" });
    if (!response.ok) return [];
    const body = (await response.json()) as AgentResponse[];
    return body.filter((agent) => agent.enabled);
  } catch {
    return [];
  }
}
