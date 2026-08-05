"use client";

import { useEffect, useRef, useState } from "react";
import type { Meeting } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import {
  MicIcon,
  MicOffIcon,
  VideoCamIcon,
  VideoOffIcon,
} from "@/components/Icons";
import { formatMeetingNumber } from "@/lib/utils";

export function PreJoin({
  meeting,
  defaultName,
  requirePasscode,
  joining,
  error,
  initialMicOn = true,
  initialCamOn = true,
  onJoin,
}: {
  meeting: Meeting;
  defaultName: string;
  requirePasscode: boolean;
  joining: boolean;
  error: string | null;
  initialMicOn?: boolean;
  initialCamOn?: boolean;
  onJoin: (opts: {
    name: string;
    passcode: string;
    stream: MediaStream | null;
    micOn: boolean;
    camOn: boolean;
  }) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [micOn, setMicOn] = useState(initialMicOn);
  const [camOn, setCamOn] = useState(initialCamOn);
  const [denied, setDenied] = useState(false);
  const [name, setName] = useState(defaultName);
  const [passcode, setPasscode] = useState("");

  useEffect(() => setName(defaultName), [defaultName]);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices
      ?.getUserMedia({ video: true, audio: true })
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        s.getAudioTracks().forEach((t) => (t.enabled = initialMicOn));
        s.getVideoTracks().forEach((t) => (t.enabled = initialCamOn));
        streamRef.current = s;
        setStream(s);
      })
      .catch(() => {
        setDenied(true);
        setMicOn(false);
        setCamOn(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (videoRef.current && stream) videoRef.current.srcObject = stream;
  }, [stream]);

  const toggleMic = () => {
    setMicOn((on) => {
      const next = !on;
      streamRef.current?.getAudioTracks().forEach((t) => (t.enabled = next));
      return next;
    });
  };
  const toggleCam = () => {
    setCamOn((on) => {
      const next = !on;
      streamRef.current?.getVideoTracks().forEach((t) => (t.enabled = next));
      return next;
    });
  };

  const canJoin = name.trim().length > 0 && (!requirePasscode || passcode.trim().length > 0);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canJoin || joining) return;
    onJoin({ name: name.trim(), passcode: passcode.trim(), stream: streamRef.current, micOn, camOn });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-zoom-dark px-4 py-8 text-white">
      <div className="w-full max-w-4xl">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold">{meeting.topic}</h1>
          <p className="mt-1 text-sm text-white/50">
            Meeting ID: {formatMeetingNumber(meeting.meeting_number)} · Hosted by{" "}
            {meeting.host.name}
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-[1.4fr_1fr]">
          <div className="relative aspect-video overflow-hidden rounded-2xl bg-zoom-panel ring-1 ring-white/10">
            {stream && camOn ? (
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full -scale-x-100 object-cover"
              />
            ) : (
              <div className="flex h-full w-full flex-col items-center justify-center gap-3">
                <Avatar name={name || "You"} size={88} />
                <p className="text-sm text-white/50">
                  {denied ? "Camera unavailable" : "Camera is off"}
                </p>
              </div>
            )}

            <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-2">
              <button
                onClick={toggleMic}
                disabled={denied}
                className={`grid h-11 w-11 place-items-center rounded-full transition-colors disabled:opacity-40 ${
                  micOn ? "bg-white/15 hover:bg-white/25" : "bg-[#E02D2D]"
                }`}
                aria-label={micOn ? "Mute mic" : "Unmute mic"}
              >
                {micOn ? <MicIcon className="h-5 w-5" /> : <MicOffIcon className="h-5 w-5" />}
              </button>
              <button
                onClick={toggleCam}
                disabled={denied}
                className={`grid h-11 w-11 place-items-center rounded-full transition-colors disabled:opacity-40 ${
                  camOn ? "bg-white/15 hover:bg-white/25" : "bg-[#E02D2D]"
                }`}
                aria-label={camOn ? "Stop video" : "Start video"}
              >
                {camOn ? <VideoCamIcon className="h-5 w-5" /> : <VideoOffIcon className="h-5 w-5" />}
              </button>
            </div>
          </div>

          <form
            onSubmit={submit}
            className="flex flex-col justify-center gap-4 rounded-2xl bg-zoom-panel p-6 ring-1 ring-white/10"
          >
            <div>
              <label className="mb-1.5 block text-sm font-medium text-white/80" htmlFor="pj-name">
                Your name
              </label>
              <input
                id="pj-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                className="w-full rounded-lg border border-white/15 bg-white/5 px-3.5 py-2.5 text-[15px] text-white placeholder:text-white/40 outline-none focus:border-zoom-blue"
                placeholder="Enter your name"
              />
            </div>

            {requirePasscode && (
              <div>
                <label className="mb-1.5 block text-sm font-medium text-white/80" htmlFor="pj-pass">
                  Meeting passcode
                </label>
                <input
                  id="pj-pass"
                  value={passcode}
                  onChange={(e) => setPasscode(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-white/5 px-3.5 py-2.5 text-[15px] text-white placeholder:text-white/40 outline-none focus:border-zoom-blue"
                  placeholder="Enter passcode"
                />
              </div>
            )}

            {error && <p className="text-sm text-[#FF6B6B]">{error}</p>}

            <button type="submit" disabled={!canJoin || joining} className="btn-primary w-full">
              {joining ? "Joining…" : "Join now"}
            </button>
            <p className="text-center text-xs text-white/40">
              {micOn ? "Mic on" : "Mic off"} · {camOn ? "Camera on" : "Camera off"}
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
