"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

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
        Welcome back - sign in to start meeting.
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
              {submitting ? "Signing in..." : "Sign In"}
            </button>
          </form>

      <p className="mt-6 text-center text-sm text-zoom-muted">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-semibold text-zoom-blue hover:underline">
          Sign up
        </Link>
      </p>
    </AuthShell>
  );
}
