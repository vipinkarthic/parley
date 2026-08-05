"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { ActionTile } from "@/components/ActionTile";
import { MeetingListItem } from "@/components/MeetingListItem";
import { JoinModal } from "@/components/JoinModal";
import { ScheduleModal } from "@/components/ScheduleModal";
import { AuthGuard } from "@/components/AuthGuard";
import { useToast } from "@/components/Toast";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import type { Meeting } from "@/lib/types";
import { CalendarIcon, PlusIcon, VideoIcon } from "@/components/Icons";

export default function DashboardPage() {
  return (
    <AuthGuard>
      <Dashboard />
    </AuthGuard>
  );
}

function Dashboard() {
  const router = useRouter();
  const toast = useToast();
  const { user } = useAuth();

  const [upcoming, setUpcoming] = useState<Meeting[]>([]);
  const [recent, setRecent] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  const [joinOpen, setJoinOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editing, setEditing] = useState<Meeting | null>(null);

  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => setNow(new Date()), []);

  const load = useCallback(async () => {
    try {
      const [up, rc] = await Promise.all([api.upcoming(), api.recent()]);
      setUpcoming(up);
      setRecent(rc);
    } catch {
      toast("Could not reach the server. Is the backend running?", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const startInstant = async () => {
    if (starting) return;
    setStarting(true);
    try {
      const meeting = await api.createInstant();
      router.push(`/meeting/${meeting.meeting_number}?host=1`);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Could not start meeting",
        "error"
      );
      setStarting(false);
    }
  };

  const greeting = (() => {
    if (!now) return "Welcome";
    const h = now.getHours();
    if (h < 12) return "Good morning";
    if (h < 18) return "Good afternoon";
    return "Good evening";
  })();

  return (
    <div className="min-h-screen bg-[#F7F8FC]">
      <Navbar />

      <main className="mx-auto max-w-[1180px] px-4 pb-16 pt-8 sm:px-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-zoom-ink sm:text-[28px]">
            {greeting}
            {user ? `, ${user.name.split(" ")[0]}` : ""}
          </h1>
          <p className="mt-1 text-[15px] text-zoom-muted">
            {now
              ? now.toLocaleDateString(undefined, {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                }) + " · "
              : ""}
            Start or join a meeting
          </p>
        </div>

        <section className="mb-10 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <ActionTile
            icon={<VideoIcon className="h-7 w-7" />}
            label="New Meeting"
            sublabel="Start an instant meeting"
            color="#FF7A59"
            onClick={startInstant}
          />
          <ActionTile
            icon={<PlusIcon className="h-7 w-7" />}
            label="Join"
            sublabel="via Meeting ID or link"
            color="#0B5CFF"
            onClick={() => setJoinOpen(true)}
          />
          <ActionTile
            icon={<CalendarIcon className="h-7 w-7" />}
            label="Schedule"
            sublabel="Plan for later"
            color="#7A5AF8"
            onClick={() => {
              setEditing(null);
              setScheduleOpen(true);
            }}
          />
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <MeetingSection
            title="Upcoming Meetings"
            emptyText="No upcoming meetings. Schedule one to see it here."
            loading={loading}
            meetings={upcoming}
            variant="upcoming"
            onEdit={(mtg) => {
              setEditing(mtg);
              setScheduleOpen(true);
            }}
            onChanged={load}
          />
          <MeetingSection
            title="Recent Meetings"
            emptyText="Your past meetings will appear here."
            loading={loading}
            meetings={recent}
            variant="recent"
            onChanged={load}
          />
        </div>
      </main>

      <JoinModal open={joinOpen} onClose={() => setJoinOpen(false)} />
      <ScheduleModal
        open={scheduleOpen}
        editing={editing}
        onClose={() => {
          setScheduleOpen(false);
          setEditing(null);
        }}
        onScheduled={load}
      />

      {starting && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 animate-fade-in">
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-white px-8 py-7 shadow-modal">
            <span className="h-8 w-8 animate-spin rounded-full border-[3px] border-zoom-line border-t-zoom-blue" />
            <p className="text-sm font-medium text-zoom-ink">
              Starting your meeting…
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function MeetingSection({
  title,
  emptyText,
  loading,
  meetings,
  variant,
  onEdit,
  onChanged,
}: {
  title: string;
  emptyText: string;
  loading: boolean;
  meetings: Meeting[];
  variant: "upcoming" | "recent";
  onEdit?: (m: Meeting) => void;
  onChanged?: () => void;
}) {
  return (
    <section className="rounded-2xl bg-white p-5 shadow-card ring-1 ring-zoom-line">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zoom-ink">{title}</h2>
        <span className="rounded-full bg-zoom-field px-2.5 py-0.5 text-xs font-medium text-zoom-muted">
          {meetings.length}
        </span>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-4 px-3 py-3.5">
              <div className="h-14 w-14 shrink-0 animate-pulse rounded-xl bg-zoom-field" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-2/3 animate-pulse rounded bg-zoom-field" />
                <div className="h-3 w-1/2 animate-pulse rounded bg-zoom-field" />
              </div>
            </div>
          ))}
        </div>
      ) : meetings.length === 0 ? (
        <p className="px-3 py-8 text-center text-sm text-zoom-muted">
          {emptyText}
        </p>
      ) : (
        <div className="-mx-2 divide-y divide-zoom-line/70">
          {meetings.map((m) => (
            <MeetingListItem
              key={m.id}
              meeting={m}
              variant={variant}
              onEdit={onEdit}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
    </section>
  );
}
