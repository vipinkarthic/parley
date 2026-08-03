"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { Avatar } from "@/components/Avatar";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { VideoIcon } from "@/components/Icons";

const DIRECTORY = [
  { name: "Priya Sharma", email: "priya.sharma@scalerailabs.com", status: "available" },
  { name: "Marcus Lee", email: "marcus.lee@scalerailabs.com", status: "in-meeting" },
  { name: "Sofia Rossi", email: "sofia.rossi@scalerailabs.com", status: "available" },
  { name: "David Chen", email: "david.chen@scalerailabs.com", status: "away" },
  { name: "Aisha Khan", email: "aisha.khan@scalerailabs.com", status: "available" },
  { name: "Tom Becker", email: "tom.becker@scalerailabs.com", status: "offline" },
] as const;

const STATUS: Record<string, { color: string; label: string }> = {
  available: { color: "#12B76A", label: "Available" },
  "in-meeting": { color: "#EF4444", label: "In a meeting" },
  away: { color: "#F79009", label: "Away" },
  offline: { color: "#98A2B3", label: "Offline" },
};

export default function ContactsPage() {
  const toast = useToast();
  const [me, setMe] = useState<User | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
  }, []);

  return (
    <PageShell
      title="Contacts"
      subtitle="Your team directory — sample data (live contacts coming soon)"
    >
      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line">
          <button className="flex w-full items-center gap-2 rounded-lg bg-zoom-field px-3 py-2.5 text-sm font-semibold text-zoom-ink">
            My Contacts
          </button>
          {["Starred", "Channels", "Apps"].map((s) => (
            <button
              key={s}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-zoom-muted transition-colors hover:bg-zoom-field"
            >
              {s}
            </button>
          ))}
        </aside>

        <section className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line">
          {me && (
            <ContactRow
              name={`${me.name} (You)`}
              email={me.email}
              status="available"
              color={me.avatar_color}
              onMeet={() => {}}
              self
            />
          )}
          {DIRECTORY.map((c) => (
            <ContactRow
              key={c.email}
              name={c.name}
              email={c.email}
              status={c.status}
              onMeet={() =>
                toast(`Inviting ${c.name.split(" ")[0]} is a placeholder`, "info")
              }
            />
          ))}
        </section>
      </div>
    </PageShell>
  );
}

function ContactRow({
  name,
  email,
  status,
  color,
  onMeet,
  self = false,
}: {
  name: string;
  email: string;
  status: string;
  color?: string;
  onMeet: () => void;
  self?: boolean;
}) {
  const s = STATUS[status];
  return (
    <div className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-zoom-field">
      <div className="relative">
        <Avatar name={name.replace(" (You)", "")} color={color} size={40} />
        <span
          className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white"
          style={{ background: s.color }}
          title={s.label}
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zoom-ink">{name}</p>
        <p className="truncate text-xs text-zoom-muted">{email}</p>
      </div>
      {!self && (
        <button
          onClick={onMeet}
          className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-zoom-blue opacity-0 transition-opacity hover:bg-[#F0F5FF] group-hover:opacity-100"
        >
          <VideoIcon className="h-4 w-4" />
          Meet
        </button>
      )}
    </div>
  );
}
