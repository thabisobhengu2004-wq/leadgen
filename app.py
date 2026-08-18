import os
import sqlite3
import time
import hmac
import hashlib
from datetime import datetime

import requests
from flask import Flask, request, jsonify, render_template, g
from dotenv import load_dotenv

load_dotenv()

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
SENDER_NAME = os.environ.get("SENDER_NAME", "")
SENDER_PHYSICAL_ADDRESS = os.environ.get("SENDER_PHYSICAL_ADDRESS", "")
APP_SECRET = os.environ.get("APP_SECRET", "change-me-please")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

app = Flask(__name__)


# ---------- Database ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT UNIQUE,
            name TEXT,
            address TEXT,
            phone TEXT,
            category TEXT,
            google_maps_url TEXT,
            possible_social_url TEXT,
            has_website INTEGER DEFAULT 0,
            website_url TEXT DEFAULT '',
            email TEXT,
            email_source TEXT,
            notes TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS suppressions (
            email TEXT PRIMARY KEY,
            reason TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            body TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS campaign_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            lead_id INTEGER,
            status TEXT,
            error TEXT,
            sent_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# ---------- Helpers ----------

def unsubscribe_token(email):
    return hmac.new(APP_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:24]


def is_suppressed(db, email):
    if not email:
        return True
    row = db.execute("SELECT 1 FROM suppressions WHERE email = ?", (email.lower(),)).fetchone()
    return row is not None


# ---------- Places search ----------

PLACE_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.internationalPhoneNumber,places.websiteUri,"
    "places.googleMapsUri,places.primaryTypeDisplayName"
)


def search_places(query, page_token=None):
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not set. Add it to your .env file.")

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": PLACE_FIELD_MASK + ",nextPageToken",
    }
    body = {"textQuery": query, "pageSize": 20}
    if page_token:
        body["pageToken"] = page_token

    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def website_looks_like_social_only(website_uri):
    """Google sometimes puts a Facebook/Instagram link in the website field
    when a business has no real website of its own."""
    if not website_uri:
        return False
    lowered = website_uri.lower()
    return "facebook.com" in lowered or "instagram.com" in lowered


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True)
    location = (data.get("location") or "").strip()
    category = (data.get("category") or "").strip()
    max_pages = min(int(data.get("max_pages", 1)), 3)  # cap to control API cost

    if not location:
        return jsonify({"error": "location is required"}), 400

    query = f"{category} in {location}" if category else f"businesses in {location}"

    db = get_db()
    saved_no_website = 0
    saved_has_website = 0
    page_token = None

    try:
        for _ in range(max_pages):
            result = search_places(query, page_token)
            places = result.get("places", [])

            for place in places:
                website = place.get("websiteUri")
                has_real_website = bool(website) and not website_looks_like_social_only(website)

                place_id = place.get("id")
                name = (place.get("displayName") or {}).get("text", "")
                address = place.get("formattedAddress", "")
                phone = place.get("internationalPhoneNumber", "")
                gmaps_url = place.get("googleMapsUri", "")
                category_name = place.get("primaryTypeDisplayName", {})
                category_name = category_name.get("text", "") if isinstance(category_name, dict) else ""
                social_url = website if website_looks_like_social_only(website) else ""
                website_url = website if has_real_website else ""

                db.execute(
                    """
                    INSERT INTO leads (place_id, name, address, phone, category,
                        google_maps_url, possible_social_url, has_website, website_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(place_id) DO UPDATE SET
                        name=excluded.name, address=excluded.address,
                        phone=excluded.phone, category=excluded.category,
                        google_maps_url=excluded.google_maps_url,
                        possible_social_url=excluded.possible_social_url,
                        has_website=excluded.has_website,
                        website_url=excluded.website_url
                    """,
                    (place_id, name, address, phone, category_name, gmaps_url,
                     social_url, int(has_real_website), website_url,
                     datetime.utcnow().isoformat()),
                )
                if has_real_website:
                    saved_has_website += 1
                else:
                    saved_no_website += 1

            db.commit()
            page_token = result.get("nextPageToken")
            if not page_token:
                break
            time.sleep(2)  # Google requires a short delay before a page token is valid

    except requests.HTTPError as e:
        return jsonify({"error": f"Google Places API error: {e.response.text}"}), 502
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "found_no_website": saved_no_website,
        "found_has_website": saved_has_website,
    })


# ---------- Leads ----------

@app.route("/api/leads", methods=["GET"])
def api_leads():
    db = get_db()
    website_filter = request.args.get("website")  # "no", "has", or omitted for all
    if website_filter == "no":
        rows = db.execute(
            "SELECT * FROM leads WHERE has_website = 0 ORDER BY created_at DESC"
        ).fetchall()
    elif website_filter == "has":
        rows = db.execute(
            "SELECT * FROM leads WHERE has_website = 1 ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/leads/<int:lead_id>", methods=["POST"])
def api_update_lead(lead_id):
    data = request.get_json(force=True)
    db = get_db()
    fields, values = [], []
    for key in ("email", "notes"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "email" in data and data["email"]:
        fields.append("email_source = ?")
        values.append(data.get("email_source", "manual"))
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    values.append(lead_id)
    db.execute(f"UPDATE leads SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    return jsonify({"ok": True})


# ---------- Campaigns ----------

def send_via_sendgrid(to_email, to_name, subject, html_body):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set. Add it to your .env file.")
    if not SENDER_EMAIL:
        raise RuntimeError("SENDER_EMAIL is not set. Add it to your .env file.")

    token = unsubscribe_token(to_email)
    unsubscribe_link = f"{APP_BASE_URL}/unsubscribe/{token}?email={to_email}"
    footer = (
        f"<hr>"
        f"<p style='font-size:12px;color:#666'>"
        f"{SENDER_NAME}, {SENDER_PHYSICAL_ADDRESS}<br>"
        f"Don't want these emails? <a href='{unsubscribe_link}'>Unsubscribe</a>."
        f"</p>"
    )
    payload = {
        "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body + footer}],
    }
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"SendGrid error {resp.status_code}: {resp.text}")


@app.route("/api/campaign/send", methods=["POST"])
def api_send_campaign():
    data = request.get_json(force=True)
    subject = data.get("subject", "")
    body_template = data.get("body", "")
    lead_ids = data.get("lead_ids", [])

    if not subject or not body_template or not lead_ids:
        return jsonify({"error": "subject, body, and lead_ids are required"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO campaigns (subject, body, created_at) VALUES (?, ?, ?)",
        (subject, body_template, datetime.utcnow().isoformat()),
    )
    campaign_id = cur.lastrowid
    db.commit()

    results = {"sent": 0, "skipped_suppressed": 0, "skipped_no_email": 0, "failed": 0}

    for lead_id in lead_ids:
        lead = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not lead:
            continue

        email = lead["email"]
        status, error = None, None

        if not email:
            results["skipped_no_email"] += 1
            status = "skipped_no_email"
        elif is_suppressed(db, email):
            results["skipped_suppressed"] += 1
            status = "skipped_suppressed"
        else:
            personalized = body_template.replace("{{business_name}}", lead["name"] or "there")
            personalized = personalized.replace("{{website_url}}", lead["website_url"] or "")
            try:
                send_via_sendgrid(email, lead["name"], subject, personalized)
                results["sent"] += 1
                status = "sent"
            except Exception as e:
                results["failed"] += 1
                status = "failed"
                error = str(e)
            time.sleep(1)  # basic rate limiting

        db.execute(
            "INSERT INTO campaign_sends (campaign_id, lead_id, status, error, sent_at) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, lead_id, status, error, datetime.utcnow().isoformat()),
        )
        db.commit()

    return jsonify({"campaign_id": campaign_id, **results})


@app.route("/unsubscribe/<token>")
def unsubscribe(token):
    email = request.args.get("email", "")
    if not email or unsubscribe_token(email) != token:
        return "Invalid unsubscribe link.", 400
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO suppressions (email, reason, created_at) VALUES (?, ?, ?)",
        (email.lower(), "user_unsubscribed", datetime.utcnow().isoformat()),
    )
    db.commit()
    return f"{email} has been unsubscribed and will not receive further emails."


# ---------- Frontend ----------

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
