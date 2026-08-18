# No-website lead finder

A local dashboard: search a place (e.g. "Johannesburg"), it pulls business
listings from Google and keeps only the ones without a real website, you fill
in emails as you find them, then send a tracked campaign with unsubscribe
handling built in.

**Read the compliance note at the bottom before sending anything in bulk.**

## 1. Install

Requires Python 3.9+.

```bash
cd leadgen-app
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in the values (steps below).

## 2. Get a Google Places API key

1. Go to console.cloud.google.com and create a project (or use an existing one).
2. Enable **"Places API (New)"** — search for it in the API library. Note: Google
   no longer allows enabling the old "Places API" on new projects, so make sure
   you pick the one labelled "(New)".
3. Go to **APIs & Services → Credentials → Create credentials → API key**.
4. Restrict the key to the Places API (New) for security.
5. Set up billing on the project — Google requires a billing account even
   though there's a monthly free tier. Check current pricing at
   https://mapsplatform.google.com/pricing/ before running large searches;
   each search in this app uses one Text Search call per 20 results.
6. Paste the key into `.env` as `GOOGLE_PLACES_API_KEY`.

## 3. Get a SendGrid account (for sending)

1. Sign up at sendgrid.com (has a free tier for low volume).
2. Go to **Settings → Sender Authentication** and verify either a single
   sender email or your whole domain — SendGrid will reject sends from an
   unverified address.
3. Go to **Settings → API Keys → Create API Key** (Mail Send permission is
   enough).
4. Paste the key into `.env` as `SENDGRID_API_KEY`, and fill in
   `SENDER_EMAIL`, `SENDER_NAME`, and `SENDER_PHYSICAL_ADDRESS` with your real
   details — these are legally required in the footer of marketing email in
   most places.

## 4. Run it

```bash
python app.py
```

Open http://localhost:5000

## How it works

1. **Search** — type a location (and optionally a category like "plumbers")
   and hit Search. It queries Google and keeps every result, tagging each one
   as "no website" or "has website" (a Facebook/Instagram link in the website
   field counts as "no website" — it's kept as a lead but flagged separately
   since it's a social page, not a site). Use the tabs above the leads table
   to switch between the two groups, or view all. The "has website" group is
   useful if you also offer redesigns/revamps — same search, two pitches.
2. **Add emails** — Google doesn't return email addresses, so this step is
   manual by design (see note below on why). Each lead has quick links to
   its Google Maps listing, its Facebook/Instagram page if found, and a
   pre-built Google search to help you find contact info fast.
3. **Send** — select leads with an email, write a subject and body
   (`{{business_name}}` gets replaced per-recipient), and send. Every email
   gets an automatic footer with your sender identity and a working
   unsubscribe link; anyone who unsubscribes is permanently skipped in future
   sends.

## Why email-finding isn't automated

Two reasons this app doesn't try to scrape emails automatically:

- **Reliability** — scraping Facebook/Instagram pages or guessing email
  patterns without a company domain produces a lot of wrong addresses, which
  hurts your sender reputation and deliverability.
- **Platform terms** — automated scraping of Facebook/Instagram/LinkedIn
  pages generally violates their terms of service.

The quick-search links are there so a human can verify the right address
in a few seconds instead.

## Compliance — read this before sending in bulk

This isn't legal advice, and you should get a real legal opinion before
running a campaign at any scale, but the short version for South Africa:

**POPIA (South Africa's data protection law) treats unsolicited marketing
email as opt-in, not opt-out — and this applies to business email addresses,
not just individuals.** Section 69 generally prohibits emailing someone for
marketing purposes unless they've already consented or are an existing
customer. Scraping addresses from Google/directories and cold-emailing them
does not meet that bar under the current guidance from South Africa's
Information Regulator.

Practical implications:
- Cold **calling** is opt-out (you can call, but must stop if asked and
  check any do-not-contact registry) — often a lower-risk first channel.
- Physical mail or in-person outreach is regulated more loosely than email.
- If you want to use email, consider using it after an initial contact
  (call, visit, referral) where the business has effectively agreed to hear
  more from you, and always keep the unsubscribe mechanism working.

This app enforces the unsubscribe/suppression side of compliance
automatically, but it can't make the underlying consent question go away —
that's a decision for you and a lawyer familiar with POPIA.
