/**
 * Security headers.
 *
 * Neither tier set any before this: no CSP, no framing policy, and - because
 * an invite link can carry the meeting passcode - no Referrer-Policy either,
 * so the full URL was sent onward to any third-party origin the page touched.
 *
 * The CSP is deliberately not a bare `default-src 'self'`: Next's App Router
 * ships inline bootstrap scripts and styles, so 'unsafe-inline' is the price
 * of a policy that does not break the app. It still closes object/frame/base
 * and pins where scripts and connections may go, which is what stops an
 * injected tag from reaching an attacker's origin.
 */
const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";
const wsBase = apiBase.startsWith("https")
  ? "wss" + apiBase.slice(5)
  : apiBase.startsWith("http")
    ? "ws" + apiBase.slice(4)
    : "";

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  ["connect-src 'self'", apiBase, wsBase].filter(Boolean).join(" "),
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Permissions-Policy",
            value: "geolocation=(), microphone=(self), camera=(self)",
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
