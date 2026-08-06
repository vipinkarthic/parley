"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { CheckIcon } from "@/components/Icons";

export default function SignupPage() {
  const router = useRouter();
  const { user, loading, completeAuth } = useAuth();

  const [step, setStep] = useState<"details" | "otp">("details");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  const requestOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.requestSignupOtp(name.trim(), email.trim(), password);
      setDevCode(res.dev_code);
      setInfo(
        res.email_sent
          ? `We sent a 6-digit code to ${email.trim()}.`
          : "Dev mode: use the code shown below."
      );
      setStep("otp");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not start signup. Try again."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { token, user: u } = await api.verifySignupOtp(email.trim(), code.trim());
      completeAuth(token, u);
      router.replace("/");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Verification failed. Try again."
      );
      setSubmitting(false);
    }
  };

  const resend = async () => {
    setError(null);
    try {
      const res = await api.resendSignupOtp(email.trim());
      setDevCode(res.dev_code);
      setInfo(res.email_sent ? "A new code is on its way." : "New dev code below.");
    } catch {
      setError("Could not resend the code.");
    }
  };

  return (
    <AuthShell
      headerRight={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-zoom-blue hover:underline">
            Sign In
          </Link>
        </>
      }
    >
      {step === "details" ? (
        <>
          <h1 className="text-[28px] font-semibold text-zoom-ink">
            Get started with Zoom
          </h1>
          <p className="mt-1 text-sm text-zoom-muted">
            We&apos;ll email you a code to verify it&apos;s really you.
          </p>
              <form onSubmit={requestOtp} className="mt-8 space-y-4">
                <div>
                  <label className="label" htmlFor="name">
                    Full name
                  </label>
                  <input
                    id="name"
                    autoFocus
                    className="input"
                    placeholder="Jane Doe"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={120}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="email">
                    Email address
                  </label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
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
                    autoComplete="new-password"
                    className="input"
                    placeholder="At least 6 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>

                {error && <p className="text-sm text-[#EF4444]">{error}</p>}

                <button
                  type="submit"
                  disabled={
                    !name.trim() ||
                    !email.trim() ||
                    password.length < 6 ||
                    submitting
                  }
                  className="btn-primary w-full"
                >
                  {submitting ? "Sending code..." : "Continue"}
                </button>
              </form>
            </>
          ) : (
            <>
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-[#EEF3FF] text-zoom-blue">
                <CheckIcon className="h-6 w-6" />
              </div>
              <h1 className="text-center text-[26px] font-bold text-zoom-ink">
                Verify your email
              </h1>
              {info && (
                <p className="mt-1 text-center text-sm text-zoom-muted">{info}</p>
              )}
              {devCode && (
                <div className="mt-4 rounded-lg border border-dashed border-zoom-blue bg-[#EEF3FF] px-4 py-2.5 text-center text-sm">
                  <span className="text-zoom-muted">Dev code: </span>
                  <span className="font-bold tracking-widest text-zoom-blue">
                    {devCode}
                  </span>
                </div>
              )}

              <form onSubmit={verify} className="mt-6 space-y-4">
                <input
                  autoFocus
                  inputMode="numeric"
                  maxLength={6}
                  className="input text-center text-2xl font-bold tracking-[0.5em]"
                  placeholder="••••••"
                  value={code}
                  onChange={(e) =>
                    setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                  }
                />

                {error && <p className="text-sm text-[#EF4444]">{error}</p>}

                <button
                  type="submit"
                  disabled={code.length !== 6 || submitting}
                  className="btn-primary w-full"
                >
                  {submitting ? "Verifying..." : "Verify & Create Account"}
                </button>
              </form>

              <div className="mt-5 flex items-center justify-between text-sm">
                <button
                  onClick={() => {
                    setStep("details");
                    setCode("");
                    setError(null);
                  }}
                  className="text-zoom-muted hover:text-zoom-ink"
                >
                  ← Change details
                </button>
                <button onClick={resend} className="font-medium text-zoom-blue hover:underline">
                  Resend code
                </button>
              </div>
            </>
          )}
    </AuthShell>
  );
}
