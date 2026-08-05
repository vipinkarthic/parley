"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { Avatar } from "@/components/Avatar";
import { api, ApiError } from "@/lib/api";
import type { Contact } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/Toast";
import { SearchIcon, VideoIcon } from "@/components/Icons";

const STATUS: Record<string, { color: string; label: string }> = {
  available: { color: "#12B76A", label: "Available" },
  "in-meeting": { color: "#EF4444", label: "In a meeting" },
};

export default function ContactsPage() {
  const router = useRouter();
  const toast = useToast();
  const { user } = useAuth();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api
      .contacts()
      .then(setContacts)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const meet = async (c: Contact) => {
    if (starting) return;
    setStarting(true);
    try {
      const meeting = await api.createInstant();
      await navigator.clipboard.writeText(meeting.invite_link).catch(() => {});
      toast(`Meeting started — invite link copied to share with ${c.name.split(" ")[0]}`, "success");
      router.push(`/meeting/${meeting.meeting_number}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start meeting", "error");
      setStarting(false);
    }
  };

  const filtered = contacts.filter(
    (c) =>
      c.name.toLowerCase().includes(query.toLowerCase()) ||
      c.email.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <PageShell title="Contacts" subtitle="Everyone on your Zoom Clone workspace">
      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line">
          <button className="flex w-full items-center gap-2 rounded-lg bg-zoom-field px-3 py-2.5 text-sm font-semibold text-zoom-ink">
            All Contacts
            <span className="ml-auto rounded-full bg-white px-2 py-0.5 text-xs text-zoom-muted">
              {contacts.length}
            </span>
          </button>
          {["Starred", "Channels", "Apps"].map((s) => (
            <button
              key={s}
              onClick={() => toast(`${s} is coming soon`, "info")}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-zoom-muted transition-colors hover:bg-zoom-field"
            >
              {s}
            </button>
          ))}
        </aside>

        <section className="rounded-2xl bg-white shadow-card ring-1 ring-zoom-line">
          <div className="border-b border-zoom-line p-3">
            <div className="flex items-center gap-2 rounded-lg bg-zoom-field px-3 py-2">
              <SearchIcon className="h-4 w-4 text-zoom-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search contacts"
                className="w-full bg-transparent text-sm text-zoom-ink outline-none placeholder:text-zoom-subtle"
              />
            </div>
          </div>

          <div className="p-2">
            {user && (
              <ContactRow
                name={`${user.name} (You)`}
                email={user.email}
                color={user.avatar_color}
                status="available"
                self
              />
            )}

            {loading ? (
              [0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-2.5">
                  <div className="h-10 w-10 animate-pulse rounded-full bg-zoom-field" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-3.5 w-1/3 animate-pulse rounded bg-zoom-field" />
                    <div className="h-3 w-1/2 animate-pulse rounded bg-zoom-field" />
                  </div>
                </div>
              ))
            ) : filtered.length === 0 ? (
              <p className="px-3 py-10 text-center text-sm text-zoom-muted">
                {contacts.length === 0
                  ? "No other users yet. Invite teammates to sign up!"
                  : "No contacts match your search."}
              </p>
            ) : (
              filtered.map((c) => (
                <ContactRow
                  key={c.id}
                  name={c.name}
                  email={c.email}
                  color={c.avatar_color}
                  status={c.status}
                  onMeet={() => meet(c)}
                  meetDisabled={starting}
                />
              ))
            )}
          </div>
        </section>
      </div>
    </PageShell>
  );
}

function ContactRow({
  name,
  email,
  color,
  status,
  onMeet,
  meetDisabled,
  self = false,
}: {
  name: string;
  email: string;
  color?: string;
  status: string;
  onMeet?: () => void;
  meetDisabled?: boolean;
  self?: boolean;
}) {
  const s = STATUS[status] ?? STATUS.available;
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
        <p className="truncate text-xs text-zoom-muted">
          {email} · {s.label}
        </p>
      </div>
      {!self && onMeet && (
        <button
          onClick={onMeet}
          disabled={meetDisabled}
          className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-zoom-blue opacity-0 transition-opacity hover:bg-[#F0F5FF] group-hover:opacity-100 disabled:opacity-40"
        >
          <VideoIcon className="h-4 w-4" />
          Meet
        </button>
      )}
    </div>
  );
}
