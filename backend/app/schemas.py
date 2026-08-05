"""Pydantic request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    avatar_color: str


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    avatar_color: str
    status: str


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
    password: str = Field(..., min_length=6, max_length=128)


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
    passcode: str | None = None


class ParticipantJoinOut(ParticipantOut):
    """Join response — includes the private WebSocket token (not exposed in
    the general participants list)."""
    ws_token: str
    is_meeting_host: bool


class ScheduledMeetingUpdate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    start_time: datetime
    duration: int = Field(default=30, ge=5, le=1440)


class MeetingBase(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class InstantMeetingCreate(MeetingBase):
    topic: str = Field(default="My Meeting", max_length=200)


class ScheduledMeetingCreate(MeetingBase):
    start_time: datetime
    duration: int = Field(default=30, ge=5, le=1440)


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meeting_number: str
    topic: str
    description: str | None
    passcode: str | None
    meeting_type: str
    status: str
    start_time: datetime | None
    duration: int
    created_at: datetime
    host: UserOut
    invite_link: str
    participant_count: int
