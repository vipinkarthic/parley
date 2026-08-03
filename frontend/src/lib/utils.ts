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

function to12h(d: Date): string {
  let h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ampm}`;
}

export function formatMeetingTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const startOfDay = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dayDiff = Math.round(
    (startOfDay(d) - startOfDay(now)) / (1000 * 60 * 60 * 24)
  );
  const time = to12h(d);
  if (dayDiff === 0) return `Today, ${time}`;
  if (dayDiff === 1) return `Tomorrow, ${time}`;
  if (dayDiff === -1) return `Yesterday, ${time}`;
  return `${WEEKDAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}, ${time}`;
}

export function dateParts(iso: string | null): { month: string; day: string } {
  if (!iso) return { month: "", day: "" };
  const d = new Date(iso);
  return { month: MONTHS[d.getMonth()], day: d.getDate().toString() };
}

export function colorFromName(name: string): string {
  const palette = [
    "#0B5CFF", "#FF7A59", "#12B76A", "#7A5AF8",
    "#F79009", "#EF4444", "#06AED4", "#EC4899",
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return palette[Math.abs(hash) % palette.length];
}

export function invitationText(m: {
  host: { name: string };
  topic: string;
  start_time: string | null;
  invite_link: string;
  meeting_number: string;
  passcode: string | null;
}): string {
  const when = m.start_time ? formatMeetingTime(m.start_time) : null;
  return [
    `${m.host.name} is inviting you to a Zoom meeting.`,
    "",
    `Topic: ${m.topic}`,
    when ? `Time: ${when}` : null,
    "",
    "Join Zoom Meeting",
    m.invite_link,
    "",
    `Meeting ID: ${formatMeetingNumber(m.meeting_number)}`,
    m.passcode ? `Passcode: ${m.passcode}` : null,
  ]
    .filter((l) => l !== null)
    .join("\n");
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
