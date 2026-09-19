import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:12345@localhost:5432/meetcheck",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Auto-logout organizers after this long with no activity.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # Base URL used to build the public attendance link shown to organizers
    # and encoded into the QR code. Override via .env once you know the
    # real address people will use (e.g. http://192.168.8.250:8091).
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

    ORG_NAME = os.environ.get("ORG_NAME", "MeetCheck")

    # Comma-separated list of email addresses allowed to self-register an
    # organizer account at /register (e.g. "admin@mkrh.go.ke,it@mkrh.go.ke").
    # Same pattern as SupplyLink/Afya Link's ACCOUNT_CREATOR_EMAILS. If this
    # is left empty, /register refuses all sign-ups -- add accounts by
    # setting this instead of leaving registration open.
    ACCOUNT_CREATOR_EMAILS = {
        e.strip().lower()
        for e in os.environ.get("ACCOUNT_CREATOR_EMAILS", "").split(",")
        if e.strip()
    }
