import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});

export const VideoIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="2" y="6" width="13" height="12" rx="2.5" />
    <path d="M15 10.5 21.2 7.2a.6.6 0 0 1 .9.5v8.6a.6.6 0 0 1-.9.5L15 13.5Z" />
  </svg>
);

export const PlusIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const CalendarIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="3" y="4.5" width="18" height="16" rx="2.5" />
    <path d="M3 9h18M8 3v3M16 3v3" />
  </svg>
);

export const ScreenShareIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="3" y="4" width="18" height="13" rx="2.5" />
    <path d="M8 21h8M12 17v4M12 12V7m0 0-2.2 2.2M12 7l2.2 2.2" />
  </svg>
);

export const MicIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);

export const MicOffIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 9v-.5a3 3 0 0 1 6 0V11m0 3a3 3 0 0 1-4.5 1.5" />
    <path d="M5 11a7 7 0 0 0 10.5 6M19 11a7 7 0 0 1-.3 2M12 18v3" />
    <path d="m3 3 18 18" />
  </svg>
);

export const VideoCamIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="2" y="6" width="13" height="12" rx="2.5" />
    <path d="M15 10.5 21.2 7.2a.6.6 0 0 1 .9.5v8.6a.6.6 0 0 1-.9.5L15 13.5Z" />
  </svg>
);

export const VideoOffIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M15 13.5 21.2 16.8a.6.6 0 0 0 .9-.5V7.7a.6.6 0 0 0-.9-.5L15 10.5" />
    <path d="M2 8.5A2.5 2.5 0 0 1 4.5 6H12M15 15v.5A2.5 2.5 0 0 1 12.5 18H4.5A2.5 2.5 0 0 1 2 15.5V12" />
    <path d="m3 3 18 18" />
  </svg>
);

export const UsersIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 5.2a3.2 3.2 0 0 1 0 6.1M17.5 19a5.5 5.5 0 0 0-2-4.3" />
  </svg>
);

export const ChatIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-4 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" />
  </svg>
);

export const PhoneEndIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M2.5 13.5c5.2-4 13.8-4 19 0 .8.6 1 1.2.5 2l-1.3 1.9c-.4.6-1 .7-1.7.4l-2.7-1.1c-.6-.2-.9-.7-.9-1.3v-1.6c-2.8-.9-5.9-.9-8.8 0v1.6c0 .6-.3 1.1-.9 1.3l-2.7 1.1c-.7.3-1.3.2-1.7-.4L.3 15.5c-.5-.8-.3-1.4.5-2Z" />
  </svg>
);

export const CopyIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
  </svg>
);

export const CheckIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="m5 12.5 4.5 4.5L19 6.5" />
  </svg>
);

export const SettingsIcon = (p: P) => (
  <svg
    width={24}
    height={24}
    viewBox="0 0 24 24"
    fill="currentColor"
    {...p}
  >
    <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.49.49 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.49.49 0 0 0-.59.22L2.74 8.87a.49.49 0 0 0 .12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.49.49 0 0 0-.12-.61l-2.01-1.58ZM12 15.6a3.6 3.6 0 1 1 0-7.2 3.6 3.6 0 0 1 0 7.2Z" />
  </svg>
);

export const SearchIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.2-3.2" />
  </svg>
);

export const CloseIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const ChevronDownIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

export const LinkIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M10 13a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 0 0-5.7-5.7L11 6" />
    <path d="M14 11a4 4 0 0 0-5.7 0L5.5 13.8a4 4 0 0 0 5.7 5.7L13 18" />
  </svg>
);

export const ClockIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.5 2" />
  </svg>
);

export const ShieldIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 3 5 6v5.5c0 4 2.8 7.4 7 8.5 4.2-1.1 7-4.5 7-8.5V6l-7-3Z" />
    <path d="m9.2 12 2 2 3.6-3.6" />
  </svg>
);

export const HandIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M8 11V5.5a1.5 1.5 0 0 1 3 0V11m0 0V4.5a1.5 1.5 0 0 1 3 0V11m0-.5V6a1.5 1.5 0 0 1 3 0v6.5c0 3.6-2.4 6.5-6 6.5-2.2 0-3.6-.9-5-2.6l-2.2-3c-.6-.9.3-2.2 1.5-1.8L8 13" />
  </svg>
);

export const MoreIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" />
  </svg>
);

export const ArrowRightIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const PinIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 4h6l-1 5 3 3v2h-5v5l-1 1-1-1v-5H4v-2l3-3-1-5Z" />
  </svg>
);
