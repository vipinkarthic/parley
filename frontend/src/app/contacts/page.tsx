"use client";

import Link from "next/link";
import { PageShell } from "@/components/PageShell";
import { SoonBadge } from "@/components/SoonBadge";
import { UsersIcon } from "@/components/Icons";

export default function ContactsPage() {
  return (
    <PageShell title="Contacts" subtitle="Your people, all in one place">
      <div className="mx-auto mt-6 max-w-xl rounded-2xl bg-white p-10 text-center shadow-card ring-1 ring-parley-line">
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-parley-tint text-parley-brand">
          <UsersIcon className="h-8 w-8" />
        </div>
        <div className="mt-5 flex items-center justify-center gap-2">
          <h2 className="text-xl font-semibold text-parley-ink">Contacts</h2>
          <SoonBadge />
        </div>
        <p className="mx-auto mt-2 max-w-sm text-[15px] leading-relaxed text-parley-muted">
          A directory of your teammates with presence and one-click calling is on
          the way. For now, start or schedule a meeting and share the invite link
          to bring people in.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Link href="/" className="btn-primary">
            Start a meeting
          </Link>
          <Link href="/meetings" className="btn-outline">
            View meetings
          </Link>
        </div>
      </div>
    </PageShell>
  );
}
