"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

/**
 * The fragment is never sent to a server, and router.replace drops it unless
 * carried over. The old query form is upgraded on the way through.
 */
export default function JoinRedirect() {
  const params = useParams<{ number: string }>();
  const search = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const query = new URLSearchParams(search.toString());
    const legacyPasscode = query.get("pwd") || "";
    query.delete("pwd");

    const hash =
      typeof window !== "undefined"
        ? window.location.hash.replace(/^#/, "")
        : "";
    const fragmentPasscode = new URLSearchParams(hash).get("pwd") || "";

    const passcode = fragmentPasscode || legacyPasscode;
    const qs = query.toString();

    router.replace(
      `/meeting/${params.number}` +
        (qs ? `?${qs}` : "") +
        (passcode ? `#pwd=${encodeURIComponent(passcode)}` : "")
    );
  }, [params.number, search, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-parley-dark text-white">
      <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-white/20 border-t-white" />
    </div>
  );
}
