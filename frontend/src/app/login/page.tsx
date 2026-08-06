"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { Avatar } from "@/components/Avatar";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

interface DemoAccount {
  name: string;
  email: string;
  password: string;
}

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demos, setDemos] = useState<DemoAccount[]>([]);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  useEffect(() => {
    api.demoAccounts().then(setDemos).catch(() => {});
  }, []);

  const loginWith = async (acc: DemoAccount) => {
    if (submitting) return;
    setEmail(acc.email);
    setPassword(acc.password);
    setSubmitting(true);
    setError(null);
    try {
      await login(acc.email, acc.password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed.");
      setSubmitting(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong. Try again."
      );
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      headerRight={
        <>
          New to Zoom?{" "}
          <Link href="/signup" className="font-semibold text-zoom-blue hover:underline">
            Sign Up Free
          </Link>
        </>
      }
    >
      <h1 className="text-[28px] font-semibold text-zoom-ink">Sign in</h1>
      <p className="mt-1 text-sm text-zoom-muted">
        Welcome back — sign in to start meeting.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="label" htmlFor="email">
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                autoFocus
                className="input"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                className="input"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && <p className="text-sm text-[#EF4444]">{error}</p>}

            <button
              type="submit"
              disabled={!email.trim() || !password || submitting}
              className="btn-primary w-full"
            >
              {submitting ? "Signing in…" : "Sign In"}
            </button>
          </form>

          {demos.length > 0 && (
            <div className="mt-6 rounded-xl border border-dashed border-zoom-line bg-zoom-field/60 p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zoom-muted">
                Demo accounts · one-click login
              </p>
              <div className="space-y-1.5">
                {demos.map((acc) => (
                  <button
                    key={acc.email}
                    type="button"
                    onClick={() => loginWith(acc)}
                    disabled={submitting}
                    className="flex w-full items-center gap-2.5 rounded-lg bg-white px-2.5 py-2 text-left ring-1 ring-zoom-line transition-colors hover:bg-[#F0F5FF] disabled:opacity-60"
                  >
                    <Avatar name={acc.name} size={30} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-zoom-ink">
                        {acc.name}
                      </span>
                      <span className="block truncate text-xs text-zoom-muted">
                        {acc.email}
                      </span>
                    </span>
                    <span className="text-xs font-semibold text-zoom-blue">
                      Log in →
                    </span>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-center text-[11px] text-zoom-subtle">
                Password for all: <span className="font-mono">{demos[0]?.password}</span>
              </p>
            </div>
          )}

      <p className="mt-6 text-center text-sm text-zoom-muted">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-semibold text-zoom-blue hover:underline">
          Sign up
        </Link>
      </p>
    </AuthShell>
  );
}
