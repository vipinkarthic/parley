"""Pydantic request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Length only, because composition rules mostly produce Password1.
MIN_PASSWORD_LENGTH = 8

# Avatars are inline data URIs, so this is the upload limit. It is echoed to
# everyone who lists the directory.
MAX_AVATAR_URL_LENGTH = 256_000

# Free text reaching the database needs a ceiling.
MAX_DESCRIPTION_LENGTH = 2_000


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    avatar_color: str
    avatar_url: str | None = None
    pmi: str = ""


class ContactOut(BaseModel):
    """One entry in the directory of other users.

    No email, since the directory is every registered user.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_color: str
    avatar_url: str | None = None
    status: str


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_color: str | None = Field(default=None, max_length=9)
    avatar_url: str | None = Field(default=None, max_length=MAX_AVATAR_URL_LENGTH)


class ChangePassword(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pref_video_on_join: bool
    pref_join_muted: bool
    pref_mirror_video: bool
    pref_hd_video: bool
    pref_notifications: bool


class PreferencesUpdate(BaseModel):
    pref_video_on_join: bool | None = None
    pref_join_muted: bool | None = None
    pref_mirror_video: bool | None = None
    pref_hd_video: bool | None = None
    pref_notifications: bool | None = None


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=8)


class ResendOtpRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class AuthResponse(BaseModel):
    """Returned on successful login / signup verification."""

    token: str
    user: UserOut


class OtpRequestResponse(BaseModel):
    email: EmailStr
    email_sent: bool
    dev_code: str | None = None


class MeetingHostOut(BaseModel):
    """The host, as shown to anyone holding a meeting number.

    That route is unauthenticated, so only the display identity belongs here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_color: str
    avatar_url: str | None = None


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    is_host: bool
    is_muted: bool
    is_video_on: bool
    is_active: bool
    joined_at: datetime


class ParticipantJoin(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    passcode: str | None = Field(default=None, max_length=64)


class ParticipantJoinOut(ParticipantOut):
    """Join response.

    Carries the private WebSocket token, which is deliberately absent from
    the general participants list.
    """

    ws_token: str
    is_meeting_host: bool
    admission: str


class ScheduledMeetingUpdate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    start_time: datetime
    duration: int = Field(default=30, ge=5, le=1440)


class MeetingSettings(BaseModel):
    """Host-controlled per-meeting settings (host always bypasses the allow_*)."""

    model_config = ConfigDict(from_attributes=True)

    waiting_room: bool
    locked: bool
    mute_on_entry: bool
    join_before_host: bool
    allow_screen_share: bool
    allow_unmute: bool
    allow_video: bool
    allow_rename: bool
    allow_chat: bool
    allow_reactions: bool


# The settings keys, derived from the model that defines them rather than
# retyped. ws.py and crud.py both used to carry their own copy - a tuple in
# one, a set in the other - so adding an eleventh setting meant remembering
# two more places that nothing would have caught you missing.
SETTING_KEYS: tuple[str, ...] = tuple(MeetingSettings.model_fields)


class MeetingSettingsUpdate(BaseModel):
    waiting_room: bool | None = None
    locked: bool | None = None
    mute_on_entry: bool | None = None
    join_before_host: bool | None = None
    allow_screen_share: bool | None = None
    allow_unmute: bool | None = None
    allow_video: bool | None = None
    allow_rename: bool | None = None
    allow_chat: bool | None = None
    allow_reactions: bool | None = None


class MeetingBase(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)


class InstantMeetingCreate(MeetingBase):
    topic: str = Field(default="My Meeting", max_length=200)
    settings: MeetingSettingsUpdate | None = None


class ScheduledMeetingCreate(MeetingBase):
    start_time: datetime
    duration: int = Field(default=30, ge=5, le=1440)
    settings: MeetingSettingsUpdate | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meeting_number: str
    topic: str
    description: str | None
    passcode: str | None
    settings: MeetingSettings
    meeting_type: str
    status: str
    start_time: datetime | None
    duration: int
    created_at: datetime
    host: MeetingHostOut
    invite_link: str
    participant_count: int


class IceServer(BaseModel):
    """One RTCIceServer entry, spelled the way the WebRTC API expects it."""

    urls: list[str]
    username: str | None = None
    credential: str | None = None


class IceConfig(BaseModel):
    """Shaped to be passed straight into `new RTCPeerConnection(...)`."""

    iceServers: list[IceServer]
    iceCandidatePoolSize: int = 0
