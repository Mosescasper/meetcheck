import csv
import io
import math
from datetime import datetime
from functools import wraps

import qrcode
from flask import (
    Flask, render_template, redirect, url_for, request, flash,
    Response, abort, session
)
from flask_login import (
    login_user, logout_user, login_required, current_user, LoginManager
)
from flask_migrate import Migrate

from config import Config
from extensions import db, login_manager
from models import Organizer, Meeting, AttendanceRecord

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager.init_app(app)
migrate = Migrate(app, db)

with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return Organizer.query.get(int(user_id))


@app.context_processor
def inject_org_name():
    return dict(org_name=Config.ORG_NAME)


def _public_base_url():
    """Prefer an explicitly configured public URL (so the QR code/link
    always points at the address people actually use, even behind a
    router/port-forward); fall back to whatever Flask sees the request
    host as."""
    return Config.PUBLIC_BASE_URL.rstrip("/") if Config.PUBLIC_BASE_URL else request.host_url.rstrip("/")


def _distance_meters(lat1, lng1, lat2, lng2):
    """Great-circle distance between two lat/lng points, in metres."""
    r = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_geofence_form(form):
    """Shared by meeting_new/meeting_edit: reads the geofence fields out of
    a submitted form and returns (enabled, lat, lng, radius_m) or raises
    ValueError with a user-facing message if the input doesn't make sense."""
    enabled = form.get("geofence_enabled") == "on"
    lat_str = form.get("geofence_lat", "").strip()
    lng_str = form.get("geofence_lng", "").strip()
    radius_str = form.get("geofence_radius_m", "").strip()

    if not enabled:
        return False, None, None, 150

    if not lat_str or not lng_str:
        raise ValueError("Set a location (use 'Use my current location' or 'Use MKRH default') to enable the geofence.")

    try:
        lat, lng = float(lat_str), float(lng_str)
        radius = int(radius_str) if radius_str else 150
    except ValueError:
        raise ValueError("Location/radius values were invalid.")

    if radius < 10:
        radius = 10

    return True, lat, lng, radius


# ---------------------------------------------------------------------------
# Organizer auth
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    """Registration is restricted to the emails listed in
    Config.ACCOUNT_CREATOR_EMAILS (set via the ACCOUNT_CREATOR_EMAILS env
    var), same pattern as SupplyLink/Afya Link."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Name, email, and password are required.", "danger")
            return render_template("auth/register.html")

        if email not in Config.ACCOUNT_CREATOR_EMAILS:
            flash("This email is not authorized to create an organizer account.", "danger")
            return render_template("auth/register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/register.html")

        if Organizer.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return render_template("auth/register.html")

        organizer = Organizer(name=name, email=email)
        organizer.set_password(password)
        db.session.add(organizer)
        db.session.commit()

        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("meeting_list"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        organizer = Organizer.query.filter_by(email=email).first()
        if not organizer or not organizer.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html")

        login_user(organizer)
        session.permanent = True
        flash(f"Welcome back, {organizer.name}.", "success")
        return redirect(url_for("meeting_list"))

    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("meeting_list"))
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Meetings (organizer-only)
# ---------------------------------------------------------------------------

@app.route("/meetings")
@login_required
def meeting_list():
    search = request.args.get("q", "").strip()

    query = Meeting.query.filter_by(organizer_id=current_user.id)
    if search:
        query = query.filter(Meeting.title.ilike(f"%{search}%"))

    meetings = query.order_by(Meeting.created_at.desc()).all()
    return render_template("meetings/list.html", meetings=meetings, search=search)


@app.route("/meetings/new", methods=["GET", "POST"])
@login_required
def meeting_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        scheduled_for_str = request.form.get("scheduled_for", "").strip()

        if not title:
            flash("Meeting title is required.", "danger")
            return render_template("meetings/new.html")

        try:
            geofence_enabled, geofence_lat, geofence_lng, geofence_radius_m = _parse_geofence_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("meetings/new.html")

        scheduled_for_val = None
        if scheduled_for_str:
            try:
                scheduled_for_val = datetime.strptime(scheduled_for_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        meeting = Meeting(
            title=title,
            description=description or None,
            scheduled_for=scheduled_for_val,
            organizer_id=current_user.id,
            geofence_enabled=geofence_enabled,
            geofence_lat=geofence_lat,
            geofence_lng=geofence_lng,
            geofence_radius_m=geofence_radius_m,
        )
        db.session.add(meeting)
        db.session.commit()

        flash(f"Meeting '{meeting.title}' created.", "success")
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))

    return render_template("meetings/new.html")


def _get_owned_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    if meeting.organizer_id != current_user.id:
        abort(404)
    return meeting


@app.route("/meetings/<int:meeting_id>")
@login_required
def meeting_detail(meeting_id):
    meeting = _get_owned_meeting(meeting_id)
    attend_url = f"{_public_base_url()}/attend/{meeting.code}"
    return render_template("meetings/detail.html", meeting=meeting, attend_url=attend_url)


@app.route("/meetings/<int:meeting_id>/edit", methods=["GET", "POST"])
@login_required
def meeting_edit(meeting_id):
    meeting = _get_owned_meeting(meeting_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        scheduled_for_str = request.form.get("scheduled_for", "").strip()

        if not title:
            flash("Meeting title is required.", "danger")
            return render_template("meetings/edit.html", meeting=meeting)

        try:
            geofence_enabled, geofence_lat, geofence_lng, geofence_radius_m = _parse_geofence_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("meetings/edit.html", meeting=meeting)

        scheduled_for_val = None
        if scheduled_for_str:
            try:
                scheduled_for_val = datetime.strptime(scheduled_for_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        meeting.title = title
        meeting.description = description or None
        meeting.scheduled_for = scheduled_for_val
        meeting.geofence_enabled = geofence_enabled
        meeting.geofence_lat = geofence_lat
        meeting.geofence_lng = geofence_lng
        meeting.geofence_radius_m = geofence_radius_m
        db.session.commit()

        flash(f"Meeting '{meeting.title}' updated.", "success")
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))

    return render_template("meetings/edit.html", meeting=meeting)


@app.route("/meetings/<int:meeting_id>/qr.png")
@login_required
def meeting_qr(meeting_id):
    meeting = _get_owned_meeting(meeting_id)
    attend_url = f"{_public_base_url()}/attend/{meeting.code}"

    img = qrcode.make(attend_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/meetings/<int:meeting_id>/toggle", methods=["POST"])
@login_required
def meeting_toggle(meeting_id):
    meeting = _get_owned_meeting(meeting_id)
    meeting.is_open = not meeting.is_open
    db.session.commit()
    flash(f"Meeting is now {'open' if meeting.is_open else 'closed'} for attendance.", "success")
    return redirect(url_for("meeting_detail", meeting_id=meeting.id))


@app.route("/meetings/<int:meeting_id>/delete", methods=["POST"])
@login_required
def meeting_delete(meeting_id):
    meeting = _get_owned_meeting(meeting_id)
    db.session.delete(meeting)
    db.session.commit()
    flash("Meeting and its attendance records have been deleted.", "info")
    return redirect(url_for("meeting_list"))


@app.route("/meetings/<int:meeting_id>/export.csv")
@login_required
def meeting_export(meeting_id):
    meeting = _get_owned_meeting(meeting_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["First Name", "Surname", "Email", "Designation", "Department", "ID / Staff No.", "Signed In At"])
    for r in meeting.attendance_records:
        writer.writerow([
            r.first_name, r.surname, r.email, r.designation, r.department,
            r.id_number or "",
            r.signed_in_at.strftime("%Y-%m-%d %H:%M:%S") if r.signed_in_at else "",
        ])

    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in meeting.title).strip() or "meeting"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}_attendance.csv"'},
    )


# ---------------------------------------------------------------------------
# Public attendance form -- no login required
# ---------------------------------------------------------------------------

@app.route("/attend/<code>", methods=["GET", "POST"])
def attend(code):
    meeting = Meeting.query.filter_by(code=code).first()

    if not meeting:
        return render_template("attend_invalid.html"), 404

    if request.method == "POST":
        if not meeting.is_open:
            flash("This meeting is no longer accepting attendance.", "danger")
            return render_template("meetings/attend.html", meeting=meeting)

        first_name = request.form.get("first_name", "").strip()
        surname = request.form.get("surname", "").strip()
        email = request.form.get("email", "").strip()
        designation = request.form.get("designation", "").strip()
        department = request.form.get("department", "").strip()
        id_number = request.form.get("id_number", "").strip()
        signature = request.form.get("signature", "").strip()
        lat_str = request.form.get("latitude", "").strip()
        lng_str = request.form.get("longitude", "").strip()

        missing = not all([first_name, surname, email, designation, department, id_number, signature])
        if missing:
            flash("First name, surname, email, designation, department, ID / Staff No., and signature are all required.", "danger")
            return render_template("meetings/attend.html", meeting=meeting)

        latitude = longitude = None
        if lat_str and lng_str:
            try:
                latitude, longitude = float(lat_str), float(lng_str)
            except ValueError:
                latitude = longitude = None

        if meeting.geofence_enabled:
            if latitude is None or longitude is None:
                flash("This meeting requires location access to check in. Please allow location access and try again.", "danger")
                return render_template("meetings/attend.html", meeting=meeting)

            distance = _distance_meters(latitude, longitude, meeting.geofence_lat, meeting.geofence_lng)
            if distance > meeting.geofence_radius_m:
                flash(
                    f"You're about {int(distance)}m from the meeting location "
                    f"(must be within {meeting.geofence_radius_m}m to check in). "
                    "Please move closer and try again.",
                    "danger",
                )
                return render_template("meetings/attend.html", meeting=meeting)

        record = AttendanceRecord(
            meeting_id=meeting.id,
            first_name=first_name,
            surname=surname,
            email=email,
            designation=designation,
            department=department,
            id_number=id_number,
            signature=signature,
            latitude=latitude,
            longitude=longitude,
            ip_address=request.remote_addr,
        )
        db.session.add(record)
        db.session.commit()

        return render_template("meetings/attend_success.html", meeting=meeting, name=first_name)

    return render_template("meetings/attend.html", meeting=meeting)


if __name__ == "__main__":
    app.run(debug=False)