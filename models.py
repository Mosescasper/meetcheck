import secrets
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


def _generate_meeting_code():
    """Short, URL-safe, hard-to-guess code used in the public attendance
    link and QR code (e.g. /attend/aB3xQ9kP)."""
    return secrets.token_urlsafe(6)


class Organizer(UserMixin, db.Model):
    __tablename__ = "organizers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    meetings = db.relationship("Meeting", back_populates="organizer")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<Organizer {self.email}>"


class Meeting(db.Model):
    __tablename__ = "meetings"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    scheduled_for = db.Column(db.DateTime)
    code = db.Column(db.String(20), nullable=False, unique=True, index=True,
                      default=_generate_meeting_code)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey("organizers.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optional geofence: when enabled, attendees must be within
    # geofence_radius_m metres of (geofence_lat, geofence_lng) to check in.
    geofence_enabled = db.Column(db.Boolean, nullable=False, default=False)
    geofence_lat = db.Column(db.Float)
    geofence_lng = db.Column(db.Float)
    geofence_radius_m = db.Column(db.Integer, nullable=False, default=150)

    organizer = db.relationship("Organizer", back_populates="meetings")
    attendance_records = db.relationship(
        "AttendanceRecord", back_populates="meeting",
        cascade="all, delete-orphan", order_by="AttendanceRecord.signed_in_at",
    )

    @property
    def attendee_count(self):
        return len(self.attendance_records)

    def __repr__(self):
        return f"<Meeting {self.title} ({self.code})>"


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meetings.id"), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    designation = db.Column(db.String(150), nullable=False)
    department = db.Column(db.String(150), nullable=False)
    id_number = db.Column(db.String(50), nullable=False)
    signature = db.Column(db.Text, nullable=False)  # base64 PNG data URL from the signature pad
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    signed_in_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50))

    meeting = db.relationship("Meeting", back_populates="attendance_records")

    @property
    def full_name(self):
        return f"{self.first_name} {self.surname}"

    def __repr__(self):
        return f"<AttendanceRecord {self.full_name} @ meeting={self.meeting_id}>"