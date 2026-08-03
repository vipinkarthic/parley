"use client";

import { useCallback, useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { MeetingListItem } from "@/components/MeetingListItem";
import { ScheduleModal } from "@/components/ScheduleModal";
import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";
import { CalendarIcon } from "@/components/Icons";

type Tab = "upcoming" | "previous";

export default function MeetingsPage() {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [upcoming, setUpcoming] = useState<Meeting[]>([]);
  const [previous, setPrevious] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editing, setEditing] = useState<Meeting | null>(null);

  const load = useCallback(async () => {
    try {
      const [up, rc] = await Promise.all([api.upcoming(), api.recent()]);
      setUpcoming(up);
      setPrevious(rc);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const list = tab === "upcoming" ? upcoming : previous;

  return (
    <PageShell
      title="Meetings"
      subtitle="Manage your upcoming and previous meetings"
      action={
        <button
          onClick={() => {
            setEditing(null);
            setScheduleOpen(true);
          }}
          className="btn-primary"
        >
          <CalendarIcon className="h-4.5 w-4.5" />
          Schedule a Meeting
        </button>
      }
    >
      <div className="rounded-2xl bg-white shadow-card ring-1 ring-zoom-line">
        <div className="flex gap-1 border-b border-zoom-line px-4 pt-3">
          {(["upcoming", "previous"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-4 pb-3 text-[15px] font-medium capitalize transition-colors ${
                tab === t ? "text-zoom-blue" : "text-zoom-muted hover:text-zoom-ink"
              }`}
            >
              {t}
              <span className="ml-1.5 rounded-full bg-zoom-field px-2 py-0.5 text-xs">
                {t === "upcoming" ? upcoming.length : previous.length}
              </span>
              {tab === t && (
                <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-zoom-blue" />
              )}
            </button>
          ))}
        </div>

        <div className="p-4">
          {loading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-4 px-3 py-3.5">
                  <div className="h-14 w-14 animate-pulse rounded-xl bg-zoom-field" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-1/2 animate-pulse rounded bg-zoom-field" />
                    <div className="h-3 w-1/3 animate-pulse rounded bg-zoom-field" />
                  </div>
                </div>
              ))}
            </div>
          ) : list.length === 0 ? (
            <div className="py-16 text-center">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-zoom-field text-zoom-muted">
                <CalendarIcon className="h-6 w-6" />
              </div>
              <p className="text-sm text-zoom-muted">
                {tab === "upcoming"
                  ? "No upcoming meetings. Schedule one to get started."
                  : "No previous meetings yet."}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-zoom-line/70">
              {list.map((m) => (
                <MeetingListItem
                  key={m.id}
                  meeting={m}
                  variant={tab === "upcoming" ? "upcoming" : "recent"}
                  onEdit={(mtg) => {
                    setEditing(mtg);
                    setScheduleOpen(true);
                  }}
                  onChanged={load}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <ScheduleModal
        open={scheduleOpen}
        editing={editing}
        onClose={() => {
          setScheduleOpen(false);
          setEditing(null);
        }}
        onScheduled={load}
      />
    </PageShell>
  );
}
