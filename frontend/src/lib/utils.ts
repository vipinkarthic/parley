export function formatMeetingNumber(number: string): string {
  const digits = number.replace(/\D/g, "");
  if (digits.length === 11) {
    return `${digits.slice(0, 3)} ${digits.slice(3, 7)} ${digits.slice(7)}`;
  }
  return number;
}

export function parseMeetingInput(raw: string): string {
  const trimmed = raw.trim();
  const match = trimmed.match(/(?:\/j\/)?(\d[\d\s]{8,})\s*$/);
  if (match) return match[1].replace(/\s/g, "");
  return trimmed.replace(/\s/g, "");
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

export function to12Hour(date: Date): string {
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, "0");
  const suffix = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  return `${hours}:${minutes} ${suffix}`;
}

export function formatMeetingTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const now = new Date();
  const startOfDay = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const dayDiff = Math.round(
    (startOfDay(date) - startOfDay(now)) / (1000 * 60 * 60 * 24)
  );
  const time = to12Hour(date);
  if (dayDiff === 0) return `Today, ${time}`;
  if (dayDiff === 1) return `Tomorrow, ${time}`;
  if (dayDiff === -1) return `Yesterday, ${time}`;
  return `${WEEKDAYS[date.getDay()]}, ${MONTHS[date.getMonth()]} ${date.getDate()}, ${time}`;
}

export function dateParts(iso: string | null): { month: string; day: string } {
  if (!iso) return { month: "", day: "" };
  const date = new Date(iso);
  return { month: MONTHS[date.getMonth()], day: date.getDate().toString() };
}

export function colorFromName(name: string): string {
  const palette = [
    "#0E7C74", "#E8833A", "#12B76A", "#7A5AF8",
    "#F79009", "#EF4444", "#06AED4", "#EC4899",
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return palette[Math.abs(hash) % palette.length];
}

export function invitationText(meeting: {
  host: { name: string };
  topic: string;
  start_time: string | null;
  invite_link: string;
  meeting_number: string;
  passcode: string | null;
}): string {
  const when = meeting.start_time
    ? formatMeetingTime(meeting.start_time)
    : null;
  return [
    `${meeting.host.name} is inviting you to a Parley meeting.`,
    "",
    `Topic: ${meeting.topic}`,
    when ? `Time: ${when}` : null,
    "",
    "Join Parley Meeting",
    meeting.invite_link,
    "",
    `Meeting ID: ${formatMeetingNumber(meeting.meeting_number)}`,
    meeting.passcode ? `Passcode: ${meeting.passcode}` : null,
  ]
    .filter((line) => line !== null)
    .join("\n");
}

export function initials(name: string): string {
  // Parenthetical suffixes are labels, not names. Guests are stored as
  // "Demo Two (Guest)", so taking the first letter of the last word gave
  // them an avatar reading "D(" - visible on every tile in a meeting.
  const parts = name
    .replace(/\([^)]*\)/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
