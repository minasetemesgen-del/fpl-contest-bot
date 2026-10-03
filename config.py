import os

# ---------------------------------------------------------------------------
# These now read from environment variables (safer for hosting — your token
# never sits in plain text in your code or on GitHub).
#
# LOCAL TESTING: you can still hardcode fallback values below the "or" on
# each line, but delete them again before pushing to GitHub.
#
# ON RAILWAY: go to your project -> Variables tab -> add each of these:
#   BOT_TOKEN
#   ADMIN_TELEGRAM_ID
#   ENTRY_FEE_BIRR          (optional, defaults to 100)
#   PAYMENT_INSTRUCTIONS    (optional, has a default below)
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("8820934232:AAFIPFkUi9zDn63rHwF8W4D9q0IVIrLykqQ")
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN is not set. Add it as an environment variable "
        "(Railway: Project -> Variables -> BOT_TOKEN)."
    )

_admin_id = os.environ.get("364334238")
if not _admin_id:
    raise ValueError(
        "ADMIN_TELEGRAM_ID is not set. Add it as an environment variable "
        "(Railway: Project -> Variables -> ADMIN_TELEGRAM_ID)."
    )
ADMIN_TELEGRAM_ID = int(_admin_id)

ENTRY_FEE_BIRR = int(os.environ.get("ENTRY_FEE_BIRR", "100"))

PAYMENT_INSTRUCTIONS = os.environ.get(
    "PAYMENT_INSTRUCTIONS",
    "Send 100 birr via Telebirr to 09XXXXXXXX (Your Name)\n"
    "or bank transfer to Account: XXXXXXXXXX, Bank Name, Your Name.\n"
    "Then copy the transaction ID/reference from the confirmation SMS.",
)

# ---------------------------------------------------------------------------
# Chapa payment gateway — enables fully automatic payment verification.
# Sign up free at https://dashboard.chapa.co, then go to Settings -> API Keys
# to get your secret key. Use the TEST key while trying things out (starts
# with CHASECK_TEST-), then switch to the LIVE key once ready for real money.
# ---------------------------------------------------------------------------
CHAPA_SECRET_KEY = os.environ.get("CHASECK_TEST-rbxJWBUA6Rq0959T2PR00VHTs07J7UVl")
if not CHAPA_SECRET_KEY:
    raise ValueError(
        "CHAPA_SECRET_KEY is not set. Add it as an environment variable "
        "(Railway: Project -> Variables -> CHAPA_SECRET_KEY). Get it free "
        "at https://dashboard.chapa.co"
    )

# Where Chapa sends the user back after paying — doesn't need to be a real
# website, this is fine as a default since the bot checks payment status
# itself rather than relying on this page.
CHAPA_RETURN_URL = os.environ.get("CHAPA_RETURN_URL", "https://t.me/share")

# How often (in seconds) the bot checks Chapa for payment confirmations.
PAYMENT_CHECK_INTERVAL_SECONDS = int(os.environ.get("PAYMENT_CHECK_INTERVAL_SECONDS", "30"))
