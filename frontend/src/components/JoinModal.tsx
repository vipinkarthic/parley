"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Modal } from "./Modal";
import { api, ApiError } from "@/lib/api";
import { parseMeetingInput } from "@/lib/utils";

export function JoinModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const number = parseMeetingInput(value);
  const canJoin = number.length >= 9;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canJoin || checking) return;
    setChecking(true);
    setError(null);
    try {
      await api.getMeeting(number);
      onClose();
      setValue("");
      router.push(`/j/${number}`);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? "No meeting found with that ID. Check it and try again."
          : "Couldn't verify that meeting. Please try again."
      );
    } finally {
      setChecking(false);
    }
  };

  const close = () => {
    setError(null);
    setValue("");
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title="Join a meeting">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="join-id">
            Meeting ID or invite link
          </label>
          <input
            id="join-id"
            autoFocus
            className="input"
            placeholder="Enter Meeting ID or paste link"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              if (error) setError(null);
            }}
          />
          {error ? (
            <p className="mt-1.5 text-xs text-[#EF4444]">{error}</p>
          ) : (
            <p className="mt-1.5 text-xs text-zoom-muted">
              You can paste a full invite link — we&apos;ll pull out the ID.
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={close} className="btn-ghost">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canJoin || checking}
            className="btn-primary"
          >
            {checking ? "Checking…" : "Join"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
