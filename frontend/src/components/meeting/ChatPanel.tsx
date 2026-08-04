"use client";

import { useEffect, useRef, useState } from "react";
import { CloseIcon } from "@/components/Icons";

export interface ChatMessage {
  id: number;
  sender: string;
  text: string;
  self: boolean;
  time: string;
}

export function ChatPanel({
  messages,
  onSend,
  onClose,
}: {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zoom-line px-4 py-3">
        <h3 className="font-semibold text-zoom-ink">Chat</h3>
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="grid h-7 w-7 place-items-center rounded-full text-zoom-muted hover:bg-black/5"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      </div>

      <div className="scroll-thin flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 ? (
          <p className="mt-6 text-center text-sm text-zoom-muted">
            No messages yet. Say hello 👋
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={m.self ? "text-right" : ""}>
              <div className="mb-0.5 flex items-center gap-2 text-xs text-zoom-muted">
                <span className="font-medium text-zoom-ink">
                  {m.self ? "You" : m.sender}
                </span>
                <span>{m.time}</span>
              </div>
              <div
                className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                  m.self
                    ? "bg-zoom-blue text-white"
                    : "bg-zoom-field text-zoom-ink"
                }`}
              >
                {m.text}
              </div>
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} className="border-t border-zoom-line p-3">
        <div className="flex items-center gap-2">
          <input
            className="input"
            placeholder="Type a message…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button
            type="submit"
            disabled={!text.trim()}
            className="btn-primary shrink-0 !px-4"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
