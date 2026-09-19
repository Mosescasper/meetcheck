# MeetCheck — Meeting Attendance System

Organizers log in, create a meeting, and get a shareable link + QR code.
Attendees open the link or scan the QR code (no login needed), type their
name, and are marked present instantly.

## What's included

- `app.py` — routes: organizer auth, meeting CRUD, QR code generation,
  CSV export, public attendance form
- `models.py` — `Organizer`, `Meeting`, `AttendanceRecord`
- `config.py` — reads `DATABASE_URL`, `SECRET_KEY`, `PUBLIC_BASE_URL` from
  environment / `.env`
- `templates/` — all pages (dark theme, same visual family as SupplyLink)

## First-time setup

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
SECRET_KEY=change-this-to-something-random
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/meetcheck
ORG_NAME=Mwai Kibaki Hospital
PUBLIC_BASE_URL=http://192.168.8.250:8091
```

`PUBLIC_BASE_URL` matters most once you deploy this on the same desktop
setup as SupplyLink — it's the address baked into every QR code and share
link, so set it to whatever address people on the network will actually
use to reach this app (adjust the port to whichever one you run this on,
since SupplyLink is already using 8090).

Create the database (in `psql` or pgAdmin):

```sql
CREATE DATABASE meetcheck;
```

Initialize migrations and build the schema:

```powershell
$env:FLASK_APP = "app.py"
python -m flask db init
python -m flask db migrate -m "initial schema"
python -m flask db upgrade
```

Run it locally to test:

```powershell
python app.py
```

Go to `http://localhost:5000/register` and create your first organizer
account.

## Running in production (same pattern as SupplyLink)

```powershell
pip install waitress
```

Create `run_production.py`:

```python
from waitress import serve
from app import app

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=8091)
```

Run with:

```powershell
python run_production.py
```

## How organizers use it

1. Register / log in
2. **New Meeting** → give it a title (and optionally a date/time, description)
3. On the meeting's page: a QR code and a plain link are both shown —
   project the QR code on a screen, or paste the link into an email/WhatsApp
4. Attendees open the link on their own phone, type their name (ID and
   department optional), and submit — no login, no app install
5. The organizer sees the attendance list update live on refresh, and can
   **Export CSV** at any time
6. **Close Meeting** stops new check-ins (e.g. once the meeting starts)
   without deleting the record — reopen it anytime with the same button

## Notes on the current design

- Anyone can currently self-register an organizer account at `/register` —
  same as SupplyLink's original `/register` before you locked it to a
  super-admin email. Worth restricting once this goes to real institutional
  use (I can help set up an equivalent "only these emails can create
  organizer accounts" pattern, same idea as SupplyLink's `ACCOUNT_CREATOR_EMAILS`).
- Attendance isn't identity-verified — anyone who has the link can type any
  name. That's inherent to a "same link for everyone, type your name"
  design (the alternative was personalized links per person, which you
  didn't want). If duplicate or fake check-ins become a real problem later,
  we can add things like one-submission-per-device tracking, or switch to
  personalized links.
- The QR code is generated fresh on every page load (not stored as a file),
  so it always stays accurate even if `PUBLIC_BASE_URL` changes later.
