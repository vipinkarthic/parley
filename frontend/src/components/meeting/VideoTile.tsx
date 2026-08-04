"use client";

import { useEffect, useRef } from "react";
import { Avatar } from "@/components/Avatar";
import { MicOffIcon, ShieldIcon } from "@/components/Icons";

export function VideoTile({
  name,
  isSelf = false,
  isHost = false,
  muted,
  videoOn,
  speaking = false,
  hand = false,
  sharing = false,
  mirror = false,
  stream,
}: {
  name: string;
  isSelf?: boolean;
  isHost?: boolean;
  muted: boolean;
  videoOn: boolean;
  speaking?: boolean;
  hand?: boolean;
  sharing?: boolean;
  mirror?: boolean;
  stream?: MediaStream | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current && stream && videoRef.current.srcObject !== stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const showVideo = !!stream && videoOn;

  return (
    <div
      className={`group relative aspect-video overflow-hidden rounded-xl bg-zoom-panel ring-1 transition-shadow ${
        speaking ? "ring-2 ring-[#12B76A]" : "ring-white/5"
      }`}
    >
      {stream && (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted={isSelf}
          className={`h-full w-full object-cover ${mirror ? "-scale-x-100" : ""} ${
            showVideo ? "" : "invisible"
          }`}
        />
      )}
      {!showVideo && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Avatar name={name} size={72} />
        </div>
      )}

      <div className="absolute right-2 top-2 flex items-center gap-1.5">
        {sharing && (
          <span className="rounded-md bg-[#12B76A] px-1.5 py-0.5 text-[10px] font-semibold text-white">
            Sharing
          </span>
        )}
        {hand && (
          <span className="grid h-6 w-6 place-items-center rounded-md bg-[#FFD166] text-sm" title="Raised hand">
            ✋
          </span>
        )}
      </div>

      <div className="absolute bottom-2 left-2 flex max-w-[calc(100%-1rem)] items-center gap-1.5 rounded-md bg-black/55 px-2 py-1 text-xs font-medium text-white backdrop-blur-sm">
        {muted && <MicOffIcon className="h-3.5 w-3.5 text-[#FF6B6B]" />}
        <span className="truncate">
          {name}
          {isSelf ? " (You)" : ""}
        </span>
        {isHost && (
          <span className="inline-flex items-center gap-0.5 text-[#FFD166]" title="Host">
            <ShieldIcon className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
    </div>
  );
}
