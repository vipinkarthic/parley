"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { CheckIcon, CloseIcon } from "./Icons";

type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

const ToastContext = createContext<(msg: string, kind?: ToastKind) => void>(
  () => {}
);

export function useToast() {
  return useContext(ToastContext);
}

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, kind: ToastKind = "info") => {
    const id = ++counter;
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
    }, 3200);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-center gap-2.5 rounded-xl bg-zoom-ink px-4 py-3 text-sm font-medium text-white shadow-modal animate-scale-in"
          >
            <span
              className={`grid h-5 w-5 place-items-center rounded-full ${
                t.kind === "success"
                  ? "bg-[#12B76A]"
                  : t.kind === "error"
                  ? "bg-[#EF4444]"
                  : "bg-zoom-blue"
              }`}
            >
              {t.kind === "error" ? (
                <CloseIcon className="h-3 w-3" strokeWidth={3} />
              ) : (
                <CheckIcon className="h-3 w-3" strokeWidth={3} />
              )}
            </span>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
