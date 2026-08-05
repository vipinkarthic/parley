"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { Avatar } from "@/components/Avatar";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/Toast";

type PrefKey = keyof Preferences;

const ROWS: { key: PrefKey; label: string; hint: string }[] = [
  { key: "pref_video_on_join", label: "Turn on my video when joining a meeting", hint: "Applied on the pre-join screen" },
  { key: "pref_join_muted", label: "Mute my microphone when joining a meeting", hint: "Applied on the pre-join screen" },
  { key: "pref_mirror_video", label: "Mirror my video", hint: "How your own tile appears to you" },
  { key: "pref_hd_video", label: "Enable HD video", hint: "Higher quality when bandwidth allows" },
  { key: "pref_notifications", label: "Desktop notifications for meetings", hint: "Reminders and invites" },
];

function Toggle({
  on,
  disabled,
  onChange,
}: {
  on: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      onClick={onChange}
      disabled={disabled}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
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
  const { user } = useAuth();
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.preferences().then(setPrefs).catch(() => {});
  }, []);

  const toggle = async (key: PrefKey) => {
    if (!prefs || saving) return;
    const next = { ...prefs, [key]: !prefs[key] };
    setPrefs(next);
    setSaving(true);
    try {
      await api.updatePreferences({ [key]: next[key] });
    } catch {
      setPrefs(prefs);
      toast("Could not save preference", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageShell title="Settings" subtitle="Manage your profile and preferences">
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-zoom-line">
          <div className="flex items-center gap-4">
            <Avatar name={user?.name || "You"} color={user?.avatar_color} size={72} />
            <div>
              <p className="text-lg font-semibold text-zoom-ink">{user?.name || "—"}</p>
              <p className="text-sm text-zoom-muted">{user?.email || ""}</p>
              <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-[#ECFDF3] px-2 py-0.5 text-xs font-medium text-[#12B76A]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#12B76A]" />
                Available
              </span>
            </div>
          </div>
          <button
            onClick={() => toast("Profile editing is coming soon", "info")}
            className="btn-outline mt-6 w-full"
          >
            Edit profile
          </button>
        </section>

        <section className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line">
          {!prefs ? (
            [0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center justify-between px-4 py-3.5">
                <div className="h-4 w-2/3 animate-pulse rounded bg-zoom-field" />
                <div className="h-6 w-11 animate-pulse rounded-full bg-zoom-field" />
              </div>
            ))
          ) : (
            ROWS.map((row) => (
              <div
                key={row.key}
                className="flex items-center justify-between gap-4 rounded-lg px-4 py-3 hover:bg-zoom-field"
              >
                <div>
                  <p className="text-sm text-zoom-ink">{row.label}</p>
                  <p className="text-xs text-zoom-muted">{row.hint}</p>
                </div>
                <Toggle on={prefs[row.key]} disabled={saving} onChange={() => toggle(row.key)} />
              </div>
            ))
          )}
        </section>
      </div>
    </PageShell>
  );
}
