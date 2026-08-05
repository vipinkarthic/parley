"use client";

import { useEffect, useMemo, useState } from "react";
import { Modal } from "./Modal";
import { api, ApiError } from "@/lib/api";
import type { Meeting } from "@/lib/types";
import { formatMeetingNumber, formatMeetingTime } from "@/lib/utils";
import { useToast } from "./Toast";
import { CalendarIcon, CheckIcon, CopyIcon } from "./Icons";

const DURATIONS = [15, 30, 45, 60, 90, 120];

function defaults() {
  const d = new Date();
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60, 0, 0);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  };
}

export function ScheduleModal({
  open,
  onClose,
  onScheduled,
  editing = null,
}: {
  open: boolean;
  onClose: () => void;
  onScheduled: () => void;
  editing?: Meeting | null;
}) {
  const toast = useToast();
  const init = useMemo(defaults, [open]);
  const isEdit = !!editing;

  const [topic, setTopic] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState(init.date);
  const [time, setTime] = useState(init.time);
  const [duration, setDuration] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<Meeting | null>(null);

  const [optWaitingRoom, setOptWaitingRoom] = useState(true);
  const [optMuteOnEntry, setOptMuteOnEntry] = useState(false);
  const [optHostOnlyShare, setOptHostOnlyShare] = useState(false);
  const [optJoinBeforeHost, setOptJoinBeforeHost] = useState(false);

  useEffect(() => {
    if (open && editing) {
      setTopic(editing.topic);
      setDescription(editing.description || "");
      if (editing.start_time) {
        const [d, t] = editing.start_time.split("T");
        setDate(d);
        setTime((t || "00:00").slice(0, 5));
      }
      setDuration(editing.duration);
      setCreated(null);
    }
  }, [open, editing]);

  const reset = () => {
    setTopic("");
    setDescription("");
    setDate(init.date);
    setTime(init.time);
    setDuration(30);
    setCreated(null);
    setOptWaitingRoom(true);
    setOptMuteOnEntry(false);
    setOptHostOnlyShare(false);
    setOptJoinBeforeHost(false);
  };

  const close = () => {
    onClose();
    setTimeout(reset, 200);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim() || submitting) return;
    setSubmitting(true);
    try {
      const start_time = `${date}T${time}:00`;
      const payload = {
        topic: topic.trim(),
        description: description.trim() || undefined,
        start_time,
        duration,
      };
      if (editing) {
        await api.updateMeeting(editing.meeting_number, payload);
        onScheduled();
        toast("Meeting updated", "success");
        close();
      } else {
        const meeting = await api.schedule({
          ...payload,
          settings: {
            waiting_room: optWaitingRoom,
            mute_on_entry: optMuteOnEntry,
            allow_screen_share: !optHostOnlyShare,
            join_before_host: optJoinBeforeHost,
          },
        });
        setCreated(meeting);
        onScheduled();
        toast("Meeting scheduled", "success");
      }
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Failed to save meeting",
        "error"
      );
    } finally {
      setSubmitting(false);
    }
  };

  const copyLink = async () => {
    if (!created) return;
    await navigator.clipboard.writeText(created.invite_link);
    toast("Invite link copied", "success");
  };

  return (
    <Modal open={open} onClose={close} title={isEdit ? "Edit meeting" : "Schedule a meeting"} width="max-w-lg">
      {created ? (
        <div className="space-y-5">
          <div className="flex items-start gap-3 rounded-xl bg-[#ECFDF3] p-4">
            <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#12B76A] text-white">
              <CheckIcon className="h-3.5 w-3.5" strokeWidth={3} />
            </span>
            <div>
              <p className="font-semibold text-zoom-ink">{created.topic}</p>
              <p className="text-sm text-zoom-muted">
                {formatMeetingTime(created.start_time)} · {created.duration} min
              </p>
            </div>
          </div>

          <div className="space-y-3 rounded-xl border border-zoom-line p-4">
            <Row label="Meeting ID">
              {formatMeetingNumber(created.meeting_number)}
            </Row>
            <Row label="Passcode">{created.passcode}</Row>
            <div>
              <p className="label">Invite link</p>
              <div className="flex items-center gap-2">
                <input
                  readOnly
                  value={created.invite_link}
                  className="input flex-1 bg-zoom-field text-sm"
                  onFocus={(e) => e.target.select()}
                />
                <button onClick={copyLink} className="btn-outline shrink-0 !px-3">
                  <CopyIcon className="h-4 w-4" />
                  Copy
                </button>
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button onClick={close} className="btn-primary">
              Done
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label" htmlFor="s-topic">
              Topic
            </label>
            <input
              id="s-topic"
              autoFocus
              className="input"
              placeholder="e.g. Product Design Review"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="s-desc">
              Description <span className="text-zoom-subtle">(optional)</span>
            </label>
            <textarea
              id="s-desc"
              className="input min-h-[72px] resize-y"
              placeholder="What's this meeting about?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="s-date">
                Date
              </label>
              <input
                id="s-date"
                type="date"
                className="input"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="s-time">
                Time
              </label>
              <input
                id="s-time"
                type="time"
                className="input"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="s-duration">
              Duration
            </label>
            <select
              id="s-duration"
              className="input appearance-none"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            >
              {DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {d < 60
                    ? `${d} minutes`
                    : `${d / 60} hour${d >= 120 ? "s" : ""}${
                        d % 60 ? " 30 min" : ""
                      }`}
                </option>
              ))}
            </select>
          </div>
          {!isEdit && (
            <div className="rounded-xl border border-zoom-line p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zoom-muted">
                Options
              </p>
              <div className="space-y-1">
                <Opt label="Enable waiting room" checked={optWaitingRoom} onChange={setOptWaitingRoom} />
                <Opt label="Mute participants on entry" checked={optMuteOnEntry} onChange={setOptMuteOnEntry} />
                <Opt label="Only host can share screen" checked={optHostOnlyShare} onChange={setOptHostOnlyShare} />
                <Opt label="Allow participants to join before host" checked={optJoinBeforeHost} onChange={setOptJoinBeforeHost} />
              </div>
            </div>
          )}
          <div className="flex items-center justify-between pt-1">
            <span className="inline-flex items-center gap-1.5 text-xs text-zoom-muted">
              <CalendarIcon className="h-4 w-4" />
              A unique link is generated automatically.
            </span>
            <div className="flex gap-2">
              <button type="button" onClick={close} className="btn-ghost">
                Cancel
              </button>
              <button
                type="submit"
                disabled={!topic.trim() || submitting}
                className="btn-primary"
              >
                {submitting
                  ? "Saving…"
                  : isEdit
                  ? "Save changes"
                  : "Schedule"}
              </button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-zoom-muted">{label}</span>
      <span className="font-medium text-zoom-ink">{children}</span>
    </div>
  );
}

function Opt({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1 py-1.5 text-sm text-zoom-ink hover:bg-zoom-field">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-zoom-blue"
      />
      {label}
    </label>
  );
}
