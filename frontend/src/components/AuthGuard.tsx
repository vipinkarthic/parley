"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F7F8FC]">
        <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-zoom-line border-t-zoom-blue" />
      </div>
    );
  }
  return <>{children}</>;
}
