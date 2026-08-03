"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Meeting } from "@/lib/types";
import {
  dateParts,
  formatMeetingNumber,
  formatMeetingTime,
  invitationText,
} from "@/lib/utils";
import { useToast } from "./Toast";
import { ClockIcon, MoreIcon } from "./Icons";

export function MeetingListItem({
  meeting,
  variant,
  onEdit,
  onChanged,
}: {
  meeting: Meeting;
  variant: "upcoming" | "recent";
  onEdit?: (m: Meeting) => void;
  onChanged?: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const { month, day } = dateParts(meeting.start_time);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const copyInvitation = async () => {
    try {
      await navigator.clipboard.writeText(invitationText(meeting));
      toast("Invitation copied to clipboard", "success");
    } catch {
      toast("Could not copy invitation", "error");
    }
    setMenuOpen(false);
  };

  const del = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    try {
      await api.deleteMeeting(meeting.meeting_number);
      toast("Meeting deleted", "success");
      onChanged?.();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not delete", "error");
    }
    setMenuOpen(false);
  };

  return (
    <div className="flex items-center gap-4 rounded-xl px-3 py-3.5 transition-colors hover:bg-zoom-field">
      <div className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-[#EEF3FF] text-zoom-blue">
        <span className="text-[11px] font-semibold uppercase leading-none">{month}</span>
        <span className="text-xl font-bold leading-tight">{day}</span>
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-zoom-ink">{meeting.topic}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[13px] text-zoom-muted">
          <span className="inline-flex items-center gap-1">
            <ClockIcon className="h-3.5 w-3.5" />
            {formatMeetingTime(meeting.start_time)}
          </span>
          <span>ID: {formatMeetingNumber(meeting.meeting_number)}</span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {variant === "upcoming" && (
          <button
            onClick={() => router.push(`/meeting/${meeting.meeting_number}`)}
            className="btn-primary !px-4 !py-2 text-sm"
          >
            Start
          </button>
        )}

        <div className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="grid h-9 w-9 place-items-center rounded-full text-zoom-muted transition-colors hover:bg-black/5"
            aria-label="More options"
          >
            <MoreIcon className="h-5 w-5" />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-11 z-20 w-48 overflow-hidden rounded-xl border border-zoom-line bg-white py-1 shadow-modal animate-scale-in">
                <button
                  onClick={copyInvitation}
                  className="block w-full px-4 py-2.5 text-left text-sm text-zoom-ink hover:bg-zoom-field"
                >
                  Copy invitation
                </button>
                {variant === "upcoming" && onEdit && (
                  <button
                    onClick={() => {
                      onEdit(meeting);
                      setMenuOpen(false);
                    }}
                    className="block w-full px-4 py-2.5 text-left text-sm text-zoom-ink hover:bg-zoom-field"
                  >
                    Edit
                  </button>
                )}
                <button
                  onClick={del}
                  className="block w-full px-4 py-2.5 text-left text-sm text-[#EF4444] hover:bg-[#FEF3F2]"
                >
                  {confirmDelete ? "Click again to confirm" : "Delete"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
