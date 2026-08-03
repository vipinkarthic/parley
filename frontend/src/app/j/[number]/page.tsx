"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

export default function JoinRedirect() {
  const params = useParams<{ number: string }>();
  const search = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const qs = search.toString();
    router.replace(`/meeting/${params.number}${qs ? `?${qs}` : ""}`);
  }, [params.number, search, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-zoom-dark text-white">
      <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-white/20 border-t-white" />
    </div>
  );
}
