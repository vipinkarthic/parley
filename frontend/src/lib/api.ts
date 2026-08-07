import type {
  Contact,
  JoinResult,
  Meeting,
  MeetingSettings,
  Preferences,
  User,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "http://localhost:8000";

const TOKEN_KEY = "zc_token";

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
    // stale token -> clear it and bounce to /login (auth routes handle their own 401s)
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
  changePassword: (current_password: string, new_password: string) =>
    request<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
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

  join: (number: string, displayName: string, passcode?: string) =>
    request<JoinResult>(`/api/meetings/${encodeURIComponent(number)}/join`, {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, passcode: passcode ?? null }),
    }),

  endMeeting: (number: string) =>
    request<Meeting>(`/api/meetings/${encodeURIComponent(number)}/end`, {
      method: "POST",
    }),
};

export { ApiError };
