import type {
  Contact,
  JoinResult,
  Meeting,
  MeetingSettings,
  Preferences,
  User,
} from "@/lib/types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "http://localhost:8000";

const TOKEN_KEY = "parley_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  if (typeof window !== "undefined") window.localStorage.removeItem(TOKEN_KEY);
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
    }
    // A stale token: clear it and bounce to /login. Auth routes are exempt
    // because a 401 there is the answer, not a session that expired.
    if (res.status === 401 && !path.startsWith("/auth/")) {
      clearToken();
      onUnauthorized?.();
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

interface AuthResponse {
  token: string;
  user: User;
}
interface OtpResponse {
  email: string;
  email_sent: boolean;
  dev_code: string | null;
}

export const api = {
  requestSignupOtp: (name: string, email: string, password: string) =>
    request<OtpResponse>("/auth/signup/request-otp", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    }),
  resendSignupOtp: (email: string) =>
    request<OtpResponse>("/auth/signup/resend-otp", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verifySignupOtp: (email: string, code: string) =>
    request<AuthResponse>("/auth/signup/verify", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),
  updateProfile: (patch: {
    name?: string;
    avatar_color?: string;
    avatar_url?: string | null;
  }) =>
    request<User>("/api/profile", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
  startPersonalRoom: () =>
    request<Meeting>("/api/meetings/personal", { method: "POST" }),

  contacts: () => request<Contact[]>("/api/contacts"),
  preferences: () => request<Preferences>("/api/preferences"),
  updatePreferences: (patch: Partial<Preferences>) =>
    request<Preferences>("/api/preferences", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  upcoming: () => request<Meeting[]>("/api/meetings/upcoming"),
  recent: () => request<Meeting[]>("/api/meetings/recent"),
  all: () => request<Meeting[]>("/api/meetings"),

  createInstant: (topic?: string) =>
    request<Meeting>("/api/meetings/instant", {
      method: "POST",
      body: JSON.stringify({ topic: topic || "My Meeting" }),
    }),

  schedule: (payload: {
    topic: string;
    description?: string;
    start_time: string;
    duration: number;
    settings?: Partial<MeetingSettings>;
  }) =>
    request<Meeting>("/api/meetings/schedule", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getMeeting: (number: string) =>
    request<Meeting>(`/api/meetings/${encodeURIComponent(number)}`),

  updateMeeting: (
    number: string,
    payload: { topic: string; description?: string; start_time: string; duration: number }
  ) =>
    request<Meeting>(`/api/meetings/${encodeURIComponent(number)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteMeeting: (number: string) =>
    request<void>(`/api/meetings/${encodeURIComponent(number)}`, {
      method: "DELETE",
    }),

  // idempotencyKey makes a retry safe: if the first attempt reached the server
  // but its response did not reach us, replaying the same key returns that
  // participant instead of creating a second one.
  join: (
    number: string,
    displayName: string,
    passcode?: string,
    idempotencyKey?: string
  ) =>
    request<JoinResult>(`/api/meetings/${encodeURIComponent(number)}/join`, {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, passcode: passcode ?? null }),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    }),

  endMeeting: (number: string) =>
    request<Meeting>(`/api/meetings/${encodeURIComponent(number)}/end`, {
      method: "POST",
    }),
};

// A fresh idempotency key for one join attempt.
//
// crypto.randomUUID only exists in a secure context, and local development
// runs on http://<tailnet-ip>:3100, which is not one - so it would be
// undefined on exactly the setup used to test this. Falls back to
// getRandomValues, then to a timestamp, because a slightly weaker key still
// deduplicates a retry and a crash here would block joining entirely.
export function newJoinKey(): string {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === "function") return webCrypto.randomUUID();
  if (typeof webCrypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    webCrypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// --- ICE configuration ----------------------------------------------------
// The relay credentials come from the API instead of NEXT_PUBLIC_*, which is
// inlined at build time and would make a credential rotation a Vercel rebuild.

export interface IceConfig {
  iceServers: RTCIceServer[];
  iceCandidatePoolSize?: number;
}

// STUN-only, i.e. exactly what shipped before TURN existed. Used when the
// fetch fails, and by useMeeting as the value held before GET /api/ice
// answers: peers with a direct path still connect, peers behind symmetric NAT
// still cannot. Degraded, not broken.
export const STUN_ONLY: IceConfig = {
  iceServers: [
    { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
  ],
};

// One fetch per page load, shared by every peer connection. Cached as the
// promise, not the result, so N peers arriving at once make one request.
let icePromise: Promise<IceConfig> | null = null;

// The relay half is gated server side, so a guest passes what its join gave.
export function fetchIceConfig(
  participantId?: number,
  wsToken?: string
): Promise<IceConfig> {
  if (!icePromise) {
    const query =
      participantId !== undefined && wsToken
        ? `?pid=${encodeURIComponent(String(participantId))}&token=${encodeURIComponent(wsToken)}`
        : "";
    icePromise = request<IceConfig>(`/api/ice${query}`)
      .then((cfg) =>
        cfg?.iceServers?.length ? cfg : STUN_ONLY
      )
      .catch(() => STUN_ONLY);
  }
  return icePromise;
}

export { ApiError };
