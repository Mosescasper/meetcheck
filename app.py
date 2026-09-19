import csv
import io
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
    meetings = (
        Meeting.query.filter_by(organizer_id=current_user.id)
        .order_by(Meeting.created_at.desc())
        .all()
    )
    return render_template("meetings/list.html", meetings=meetings)


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
    writer.writerow(["Name", "ID Number", "Department", "Signed In At"])
    for r in meeting.attendance_records:
        writer.writerow([
            r.name, r.id_number or "", r.department or "",
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

        name = request.form.get("name", "").strip()
        id_number = request.form.get("id_number", "").strip()
        department = request.form.get("department", "").strip()

        if not name:
            flash("Please enter your name.", "danger")
            return render_template("meetings/attend.html", meeting=meeting)

        record = AttendanceRecord(
            meeting_id=meeting.id,
            name=name,
            id_number=id_number or None,
            department=department or None,
            ip_address=request.remote_addr,
        )
        db.session.add(record)
        db.session.commit()

        return render_template("meetings/attend_success.html", meeting=meeting, name=name)

    return render_template("meetings/attend.html", meeting=meeting)


if __name__ == "__main__":
    app.run(debug=False)
