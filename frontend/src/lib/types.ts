export interface User {
  id: number;
  name: string;
  email: string;
  avatar_color: string;
}

export interface MeetingSettings {
  waiting_room: boolean;
  locked: boolean;
  mute_on_entry: boolean;
  join_before_host: boolean;
  allow_screen_share: boolean;
  allow_unmute: boolean;
  allow_video: boolean;
  allow_rename: boolean;
  allow_chat: boolean;
  allow_reactions: boolean;
}

export interface Meeting {
  id: string;
  meeting_number: string;
  topic: string;
  description: string | null;
  passcode: string | null;
  settings: MeetingSettings;
  meeting_type: "instant" | "scheduled";
  status: "scheduled" | "active" | "ended";
  start_time: string | null;
  duration: number;
  created_at: string;
  host: User;
  invite_link: string;
  participant_count: number;
}

export interface Participant {
  id: number;
  display_name: string;
  is_host: boolean;
  is_muted: boolean;
  is_video_on: boolean;
  is_active: boolean;
  joined_at: string;
}

export interface JoinResult extends Participant {
  ws_token: string;
  is_meeting_host: boolean;
  admission: "admitted" | "waiting";
}

export interface WaitingPerson {
  id: number;
  displayName: string;
}

export interface Contact {
  id: number;
  name: string;
  email: string;
  avatar_color: string;
  status: "available" | "in-meeting";
}

export interface Preferences {
  pref_video_on_join: boolean;
  pref_join_muted: boolean;
  pref_mirror_video: boolean;
  pref_hd_video: boolean;
  pref_notifications: boolean;
}
