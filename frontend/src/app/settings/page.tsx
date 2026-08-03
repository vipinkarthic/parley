"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { Avatar } from "@/components/Avatar";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useToast } from "@/components/Toast";

function Toggle({ defaultOn = false }: { defaultOn?: boolean }) {
  const [on, setOn] = useState(defaultOn);
  return (
    <button
      onClick={() => setOn((v) => !v)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        on ? "bg-zoom-blue" : "bg-zoom-line"
      }`}
      aria-pressed={on}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
          on ? "left-[22px]" : "left-0.5"
        }`}
      />
    </button>
  );
}

export default function SettingsPage() {
  const toast = useToast();
  const [me, setMe] = useState<User | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
  }, []);

  return (
    <PageShell
      title="Settings"
      subtitle="Your profile · preferences are a preview and aren't saved yet"
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-zoom-line">
          <div className="flex items-center gap-4">
            <Avatar name={me?.name || "You"} color={me?.avatar_color} size={72} />
            <div>
              <p className="text-lg font-semibold text-zoom-ink">
                {me?.name || "—"}
              </p>
              <p className="text-sm text-zoom-muted">{me?.email || ""}</p>
              <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-[#ECFDF3] px-2 py-0.5 text-xs font-medium text-[#12B76A]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#12B76A]" />
                Available
              </span>
            </div>
          </div>
          <button
            onClick={() => toast("Profile editing is a placeholder", "info")}
            className="btn-outline mt-6 w-full"
          >
            Edit profile
          </button>
        </section>

        <section className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line">
          {[
            { label: "Turn on my video when joining a meeting", on: true },
            { label: "Mute my microphone when joining a meeting", on: false },
            { label: "Always show meeting controls", on: true },
            { label: "Enable HD video", on: false },
            { label: "Desktop notifications for meetings", on: true },
          ].map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between gap-4 rounded-lg px-4 py-3.5 hover:bg-zoom-field"
            >
              <span className="text-sm text-zoom-ink">{row.label}</span>
              <Toggle defaultOn={row.on} />
            </div>
          ))}
        </section>
      </div>
    </PageShell>
  );
}
