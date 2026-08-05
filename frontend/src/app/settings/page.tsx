"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { Avatar } from "@/components/Avatar";
import { api, ApiError } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/Toast";
import { formatMeetingNumber } from "@/lib/utils";
import { CopyIcon, VideoIcon } from "@/components/Icons";

const AVATAR_COLORS = [
  "#0B5CFF", "#FF7A59", "#12B76A", "#7A5AF8",
  "#F79009", "#EF4444", "#06AED4", "#EC4899",
];

type TabId = "profile" | "account" | "video" | "general" | "notifications";
const TABS: { id: TabId; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "account", label: "Account" },
  { id: "video", label: "Video & Audio" },
  { id: "general", label: "General" },
  { id: "notifications", label: "Notifications" },
];

function fileToAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read failed"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("decode failed"));
      img.onload = () => {
        const size = 256;
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d")!;
        const min = Math.min(img.width, img.height);
        ctx.drawImage(img, (img.width - min) / 2, (img.height - min) / 2, min, min, 0, 0, size, size);
        resolve(canvas.toDataURL("image/jpeg", 0.85));
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
}

function Toggle({ on, disabled, onChange }: { on: boolean; disabled?: boolean; onChange: () => void }) {
  return (
    <button
      onClick={onChange}
      disabled={disabled}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${on ? "bg-zoom-blue" : "bg-zoom-line"}`}
      aria-pressed={on}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-zoom-line">
      <h2 className="mb-4 text-lg font-semibold text-zoom-ink">{title}</h2>
      {children}
    </section>
  );
}

export default function SettingsPage() {
  const toast = useToast();
  const router = useRouter();
  const { user, setUser } = useAuth();
  const [tab, setTab] = useState<TabId>("profile");
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.preferences().then(setPrefs).catch(() => {});
  }, []);

  const togglePref = async (key: keyof Preferences) => {
    if (!prefs || saving) return;
    const next = { ...prefs, [key]: !prefs[key] };
    setPrefs(next);
    setSaving(true);
    try {
      await api.updatePreferences({ [key]: next[key] });
      if (key === "pref_notifications" && next[key] && "Notification" in window) {
        Notification.requestPermission().catch(() => {});
      }
    } catch {
      setPrefs(prefs);
      toast("Could not save preference", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageShell title="Settings" subtitle="Manage your profile and preferences">
      <div className="grid gap-6 md:grid-cols-[210px_1fr]">
        <aside className="rounded-2xl bg-white p-2 shadow-card ring-1 ring-zoom-line md:self-start">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex w-full items-center rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                tab === t.id ? "bg-zoom-field font-semibold text-zoom-ink" : "text-zoom-muted hover:bg-zoom-field"
              }`}
            >
              {t.label}
            </button>
          ))}
        </aside>

        <div className="space-y-6">
          {tab === "profile" && user && (
            <ProfileTab
              onNavigate={(n) => router.push(`/meeting/${n}`)}
              onSaved={setUser}
            />
          )}
          {tab === "account" && <AccountTab />}
          {tab === "video" && (
            <PrefsCard
              title="Video & Audio"
              prefs={prefs}
              saving={saving}
              rows={[
                { key: "pref_video_on_join", label: "Turn on my video when joining", hint: "Applied on the pre-join screen" },
                { key: "pref_mirror_video", label: "Mirror my video", hint: "How your own tile appears to you" },
                { key: "pref_hd_video", label: "Enable HD video", hint: "Requests 720p from your camera" },
              ]}
              onToggle={togglePref}
            />
          )}
          {tab === "general" && (
            <PrefsCard
              title="General"
              prefs={prefs}
              saving={saving}
              rows={[
                { key: "pref_join_muted", label: "Mute my microphone when joining", hint: "Applied on the pre-join screen" },
              ]}
              onToggle={togglePref}
            />
          )}
          {tab === "notifications" && (
            <PrefsCard
              title="Notifications"
              prefs={prefs}
              saving={saving}
              rows={[
                { key: "pref_notifications", label: "Desktop notifications", hint: "Asks for browser permission when enabled" },
              ]}
              onToggle={togglePref}
            />
          )}
        </div>
      </div>
    </PageShell>
  );
}

function PrefsCard({
  title,
  prefs,
  saving,
  rows,
  onToggle,
}: {
  title: string;
  prefs: Preferences | null;
  saving: boolean;
  rows: { key: keyof Preferences; label: string; hint: string }[];
  onToggle: (k: keyof Preferences) => void;
}) {
  return (
    <Card title={title}>
      {!prefs ? (
        <div className="space-y-3">
          {rows.map((_, i) => (
            <div key={i} className="h-6 w-full animate-pulse rounded bg-zoom-field" />
          ))}
        </div>
      ) : (
        <div className="-mx-2">
          {rows.map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-4 rounded-lg px-2 py-3 hover:bg-zoom-field">
              <div>
                <p className="text-sm text-zoom-ink">{row.label}</p>
                <p className="text-xs text-zoom-muted">{row.hint}</p>
              </div>
              <Toggle on={prefs[row.key]} disabled={saving} onChange={() => onToggle(row.key)} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ProfileTab({
  onNavigate,
  onSaved,
}: {
  onNavigate: (meetingNumber: string) => void;
  onSaved: (u: import("@/lib/types").User) => void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(user?.name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => setName(user?.name ?? ""), [user?.name]);
  if (!user) return null;

  const patch = async (body: { name?: string; avatar_color?: string; avatar_url?: string | null }) => {
    setBusy(true);
    try {
      const updated = await api.updateProfile(body);
      onSaved(updated);
      return true;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not update profile", "error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveName = async () => {
    if (!name.trim() || name.trim() === user.name) return;
    setSavingName(true);
    if (await patch({ name: name.trim() })) toast("Name updated", "success");
    setSavingName(false);
  };

  const onPhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 8_000_000) return toast("Image is too large (max 8 MB)", "error");
    try {
      const dataUrl = await fileToAvatar(file);
      if (await patch({ avatar_url: dataUrl })) toast("Photo updated", "success");
    } catch {
      toast("Could not process that image", "error");
    }
  };

  const startPersonal = async () => {
    setBusy(true);
    try {
      const m = await api.startPersonalRoom();
      onNavigate(m.meeting_number);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start room", "error");
      setBusy(false);
    }
  };

  const copyPmi = async () => {
    await navigator.clipboard.writeText(formatMeetingNumber(user.pmi));
    toast("Personal Meeting ID copied", "success");
  };

  return (
    <>
      <Card title="Profile">
        <div className="flex flex-wrap items-center gap-5">
          <Avatar name={user.name} color={user.avatar_color} src={user.avatar_url} size={80} />
          <div className="space-y-2">
            <div className="flex gap-2">
              <button onClick={() => fileRef.current?.click()} disabled={busy} className="btn-outline !py-1.5 text-sm">
                Upload photo
              </button>
              {user.avatar_url && (
                <button
                  onClick={async () => { if (await patch({ avatar_url: "" })) toast("Photo removed", "success"); }}
                  disabled={busy}
                  className="btn-ghost text-sm text-zoom-muted"
                >
                  Remove
                </button>
              )}
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={onPhoto} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zoom-muted">Colour:</span>
              {AVATAR_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => patch({ avatar_color: c })}
                  disabled={busy}
                  aria-label={`Set avatar colour ${c}`}
                  className={`h-5 w-5 rounded-full ring-2 ring-offset-1 transition ${
                    user.avatar_color === c ? "ring-zoom-ink" : "ring-transparent hover:ring-zoom-line"
                  }`}
                  style={{ background: c }}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 space-y-4">
          <div>
            <label className="label" htmlFor="p-name">Display name</label>
            <div className="flex gap-2">
              <input id="p-name" className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
              <button
                onClick={saveName}
                disabled={savingName || !name.trim() || name.trim() === user.name}
                className="btn-primary shrink-0"
              >
                {savingName ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input bg-zoom-field text-zoom-muted" value={user.email} readOnly />
          </div>
        </div>
      </Card>

      <Card title="Personal Meeting Room">
        <p className="text-sm text-zoom-muted">Your permanent meeting ID — reuse it any time.</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="rounded-lg bg-zoom-field px-3 py-2 font-mono text-lg font-semibold text-zoom-ink">
            {formatMeetingNumber(user.pmi)}
          </span>
          <button onClick={copyPmi} className="btn-outline !py-2 text-sm">
            <CopyIcon className="h-4 w-4" /> Copy
          </button>
          <button onClick={startPersonal} disabled={busy} className="btn-primary !py-2 text-sm">
            <VideoIcon className="h-4 w-4" /> Start personal room
          </button>
        </div>
      </Card>
    </>
  );
}

function AccountTab() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (next.length < 6) return toast("New password must be at least 6 characters", "error");
    if (next !== confirm) return toast("New passwords don't match", "error");
    setBusy(true);
    try {
      await api.changePassword(current, next);
      toast("Password updated", "success");
      setCurrent(""); setNext(""); setConfirm("");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change password", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Change password">
      <form onSubmit={submit} className="max-w-sm space-y-4">
        <div>
          <label className="label" htmlFor="cur">Current password</label>
          <input id="cur" type="password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        </div>
        <div>
          <label className="label" htmlFor="new">New password</label>
          <input id="new" type="password" className="input" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        </div>
        <div>
          <label className="label" htmlFor="cfm">Confirm new password</label>
          <input id="cfm" type="password" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </div>
        <button type="submit" disabled={busy || !current || !next || !confirm} className="btn-primary">
          {busy ? "Updating…" : "Update password"}
        </button>
      </form>
    </Card>
  );
}
