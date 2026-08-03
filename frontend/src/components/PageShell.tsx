import type { ReactNode } from "react";
import { Navbar } from "./Navbar";
import { AuthGuard } from "./AuthGuard";

export function PageShell({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#F7F8FC]">
        <Navbar />
        <main className="mx-auto max-w-[1180px] px-4 pb-16 pt-8 sm:px-6">
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-zoom-ink sm:text-[28px]">
                {title}
              </h1>
              {subtitle && (
                <p className="mt-1 text-[15px] text-zoom-muted">{subtitle}</p>
              )}
            </div>
            {action}
          </div>
          {children}
        </main>
      </div>
    </AuthGuard>
  );
}
