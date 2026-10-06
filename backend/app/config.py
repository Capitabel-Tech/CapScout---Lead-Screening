from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # postgresql+psycopg://user:password@host:5432/dbname
    database_url: str

    # Signs login sessions. Long random string; changing it signs everyone out.
    jwt_secret: str
    session_hours: int = 12
    # True in production (HTTPS). False only for local http://localhost development.
    cookie_secure: bool = False

    # Login lockout: this many failures within the window blocks that employee code.
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    cors_origins: list[str] = ["http://localhost:5173"]

    # Official Zoho CRM MCP server (the URL contains a secret token; backend only).
    # Sync runs only when this is set and zoho_sync_enabled is true.
    zoho_mcp_url: str | None = None
    zoho_sync_enabled: bool = True
    zoho_poll_seconds: int = 5
    zoho_max_attempts: int = 8
    zoho_call_timeout_seconds: int = 60
    # Zoho "Meeting Venue" value sent with every meeting (a Zoho picklist).
    zoho_meeting_venue: str = "Client location"
    # Optional custom fields in Zoho that hold OUR id, so a lost reply can never cause a
    # duplicate. Ask the Zoho admin to create them as text fields marked unique.
    zoho_lead_ref_field: str | None = None
    zoho_meeting_ref_field: str | None = None

    # Turning a meeting's GPS numbers into a readable place. Only the latitude and longitude are
    # sent to the map service (no customer names or details). Default: free OpenStreetMap
    # (Nominatim): fine for testing; its usage policy limits heavy use, so a paid service
    # (Google, Ola Maps, LocationIQ...) should replace it for production.
    geocoding_enabled: bool = True
    geocoding_url: str = "https://nominatim.openstreetmap.org/reverse"
    geocoding_user_agent: str = "CapScout-LeadScreening/1.0"
    geocoding_timeout_seconds: int = 8
    geocoding_max_attempts: int = 3

    # TESTING ONLY: employee code to use when a request has no valid session,
    # so the sign-in screen is skipped. Remove from .env when testing is done.
    # Refused in production (COOKIE_SECURE=true).
    dev_auto_login: str | None = None

    @model_validator(mode="after")
    def _no_auto_login_in_production(self) -> "Settings":
        if self.dev_auto_login and self.cookie_secure:
            raise ValueError("DEV_AUTO_LOGIN must not be set in production (COOKIE_SECURE=true)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
