"""
FPL Weekly Contest Telegram Bot — Fully Automatic Payments
------------------------------------------------------------
Users register their official FPL Team ID, tap a payment link (powered by
Chapa — supports Telebirr, CBE Birr, cards), and the bot automatically
checks in the background whether the payment went through. No admin action
is needed at any point — entries confirm themselves. Each gameweek, the bot
pulls live scores from the official FPL API to find the weekly winner.

HOW TO SET IT UP (no coding needed beyond setting environment variables):
1. Get your bot token from @BotFather on Telegram.
2. Get your own numeric Telegram user ID (message @userinfobot to find it).
3. Sign up free at https://dashboard.chapa.co and get your Secret Key.
4. Set BOT_TOKEN, ADMIN_TELEGRAM_ID, CHAPA_SECRET_KEY as environment
   variables (see README.md).
5. Run: python bot.py

Data is stored locally in fpl_contest.db (SQLite) — no external database needed.
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import (
    BOT_TOKEN,
    ADMIN_TELEGRAM_ID,
    ENTRY_FEE_BIRR,
    CHAPA_SECRET_KEY,
    CHAPA_RETURN_URL,
    PAYMENT_CHECK_INTERVAL_SECONDS,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = "fpl_contest.db"
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_ENTRY_HISTORY_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/history/"
CHAPA_INITIALIZE_URL = "https://api.chapa.co/v1/transaction/initialize"
CHAPA_VERIFY_URL = "https://api.chapa.co/v1/transaction/verify/{tx_ref}"


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            fpl_team_id INTEGER
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS entries (
            telegram_id INTEGER,
            gameweek INTEGER,
            paid INTEGER DEFAULT 0,
            tx_reference TEXT,
            PRIMARY KEY (telegram_id, gameweek)
        )"""
    )
    conn.commit()
    conn.close()


def db_execute(query, params=(), fetch=False, fetchone=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if fetchone:
        result = c.fetchone()
    elif fetch:
        result = c.fetchall()
    conn.commit()
    conn.close()
    return result


# ---------------------------------------------------------------------------
# FPL API helpers
# ---------------------------------------------------------------------------
def get_current_gameweek():
    """Returns the id of the currently active (or next) FPL gameweek."""
    resp = requests.get(FPL_BOOTSTRAP_URL, timeout=10)
    resp.raise_for_status()
    events = resp.json()["events"]
    for event in events:
        if event["is_current"]:
            return event["id"]
    # fallback: next event if none marked current (e.g. between seasons)
    for event in events:
        if event["is_next"]:
            return event["id"]
    return None


def get_gameweek_deadline(gameweek):
    """Returns the FPL transfer-lock deadline for a gameweek as a UTC
    datetime, or None if it can't be found. This is the same moment FPL
    itself locks everyone's squad — entries must close no later than this,
    otherwise someone could pay after watching live scores and know in
    advance whether they're winning."""
    resp = requests.get(FPL_BOOTSTRAP_URL, timeout=10)
    resp.raise_for_status()
    events = resp.json()["events"]
    for event in events:
        if event["id"] == gameweek:
            # FPL gives this as ISO 8601 UTC, e.g. "2026-10-04T10:00:00Z"
            return datetime.strptime(event["deadline_time"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
    return None


def entries_are_still_open(gameweek):
    """True only if this gameweek's FPL deadline hasn't passed yet."""
    deadline = get_gameweek_deadline(gameweek)
    if deadline is None:
        # If we can't confirm the deadline, fail safe and block entry rather
        # than risk letting someone pay in after results are already known.
        return False
    return datetime.now(timezone.utc) < deadline


def get_gameweek_score(team_id, gameweek):
    """Returns a team's points for a specific gameweek, or None if unavailable."""
    resp = requests.get(FPL_ENTRY_HISTORY_URL.format(team_id=team_id), timeout=10)
    if resp.status_code != 200:
        return None
    history = resp.json().get("current", [])
    for gw in history:
        if gw["event"] == gameweek:
            return gw["points"]
    return None


def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_TELEGRAM_ID


# ---------------------------------------------------------------------------
# Chapa payment helpers
# ---------------------------------------------------------------------------
def chapa_headers():
    return {"Authorization": f"Bearer {CHAPA_SECRET_KEY}"}


def create_payment_link(tx_ref, amount, first_name, last_name, telegram_id):
    """Asks Chapa for a checkout URL the user can tap to pay."""
    payload = {
        "amount": str(amount),
        "currency": "ETB",
        # Chapa requires an email; users don't give us one, so we use a
        # placeholder tied to their Telegram ID. example.com is a reserved
        # "documentation" domain and gets rejected by Chapa's validator, so
        # we use a real, universally-recognized domain instead. Chapa never
        # actually emails this address.
        "email": f"fplcontest.user{telegram_id}@gmail.com",
        "first_name": first_name or "FPL",
        "last_name": last_name or "Player",
        "tx_ref": tx_ref,
        "return_url": CHAPA_RETURN_URL,
        # Chapa limits customization.title to 16 characters — keep this short.
        "customization": {
            "title": "FPL Contest",
            "description": f"GW entry fee - {amount} ETB",
        },
    }
    resp = requests.post(CHAPA_INITIALIZE_URL, json=payload, headers=chapa_headers(), timeout=15)
    if resp.status_code != 200:
        # Log Chapa's actual explanation instead of just "400 Bad Request",
        # so any future issue is immediately readable in the logs.
        logger.error(f"Chapa initialize rejected ({resp.status_code}): {resp.text}")
        return None
    data = resp.json()
    if data.get("status") == "success":
        return data["data"]["checkout_url"]
    logger.error(f"Chapa initialize returned non-success: {data}")
    return None


def verify_payment(tx_ref):
    """Returns True if Chapa confirms this transaction succeeded."""
    resp = requests.get(CHAPA_VERIFY_URL.format(tx_ref=tx_ref), headers=chapa_headers(), timeout=15)
    if resp.status_code != 200:
        return False
    data = resp.json()
    return data.get("status") == "success" and data.get("data", {}).get("status") == "success"


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the FPL Weekly Contest! 🏆\n\n"
        f"Entry fee: {ENTRY_FEE_BIRR} birr per gameweek. Highest scorer that "
        "gameweek wins the prize.\n\n"
        "Commands:\n"
        "/register <your_FPL_team_id> - link your FPL team\n"
        "/pay - get your payment link (Telebirr, CBE Birr, or card)\n"
        "/mystatus - check your registration & payment status\n"
        "/leaderboard - see this gameweek's live standings\n\n"
        "Payments confirm automatically within about a minute — no need to "
        "message anyone."
    )


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /register <fpl_team_id>\n\n"
            "Find your team ID in the URL when you open 'Points' on the "
            "official FPL site, e.g. .../entry/1234567/event/1 → 1234567 is your ID."
        )
        return
    try:
        team_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid numeric team ID.")
        return

    user = update.effective_user
    db_execute(
        "INSERT INTO users (telegram_id, username, fpl_team_id) VALUES (?, ?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET fpl_team_id=excluded.fpl_team_id, username=excluded.username",
        (user.id, user.username or user.first_name, team_id),
    )
    await update.message.reply_text(
        f"✅ Registered! Your FPL team ID {team_id} is linked.\nNow run /pay to enter this gameweek."
    )


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = db_execute("SELECT fpl_team_id FROM users WHERE telegram_id=?", (user.id,), fetchone=True)
    if not row:
        await update.message.reply_text("Please /register your FPL team ID first.")
        return

    gw = get_current_gameweek()

    # Entries must close at FPL's own deadline — the same moment squads lock
    # for everyone. Without this, someone could wait, watch live scores, and
    # only pay once they know they're winning. Fail safe: if we can't
    # confirm the deadline for any reason, block entry rather than risk it.
    try:
        still_open = entries_are_still_open(gw)
    except Exception:
        logger.exception("Could not check FPL deadline")
        still_open = False
    if not still_open:
        await update.message.reply_text(
            f"⛔ Entries for GW{gw} are closed — the FPL deadline has already "
            "passed. You can enter again once the next gameweek opens."
        )
        return

    existing = db_execute(
        "SELECT paid, tx_reference FROM entries WHERE telegram_id=? AND gameweek=?",
        (user.id, gw),
        fetchone=True,
    )
    if existing and existing[0] == 1:
        await update.message.reply_text(f"You're already confirmed and entered for GW{gw}! ✅")
        return

    tx_ref = f"fplgw{gw}-{user.id}-{int(time.time())}"
    try:
        checkout_url = create_payment_link(
            tx_ref, ENTRY_FEE_BIRR, user.first_name, user.last_name, user.id
        )
    except Exception:
        logger.exception("Chapa initialize failed")
        checkout_url = None

    if not checkout_url:
        await update.message.reply_text(
            "Sorry, couldn't create a payment link right now — please try again in a moment."
        )
        return

    db_execute(
        "INSERT INTO entries (telegram_id, gameweek, paid, tx_reference) VALUES (?, ?, 0, ?) "
        "ON CONFLICT(telegram_id, gameweek) DO UPDATE SET tx_reference=excluded.tx_reference",
        (user.id, gw, tx_ref),
    )
    await update.message.reply_text(
        f"💰 Entry fee: {ENTRY_FEE_BIRR} birr for Gameweek {gw}\n\n"
        f"Tap to pay (Telebirr, CBE Birr, or card):\n{checkout_url}\n\n"
        "Once payment completes, you'll be entered automatically within a "
        f"minute — no need to do anything else. Check /mystatus anytime."
    )


async def check_pending_payments(context: ContextTypes.DEFAULT_TYPE):
    """Background job: automatically verifies all pending payments with Chapa
    and confirms entries with zero admin involvement."""
    pending = db_execute(
        "SELECT telegram_id, gameweek, tx_reference FROM entries WHERE paid=0", fetch=True
    )
    for telegram_id, gw, tx_ref in pending:
        try:
            if verify_payment(tx_ref):
                db_execute(
                    "UPDATE entries SET paid=1 WHERE telegram_id=? AND gameweek=?",
                    (telegram_id, gw),
                )
                await context.bot.send_message(
                    telegram_id,
                    f"✅ Payment confirmed automatically! You're entered in GW{gw}. Good luck!",
                )
                logger.info(f"Auto-confirmed payment for {telegram_id}, GW{gw}")
        except Exception:
            logger.exception(f"Payment verify failed for tx_ref {tx_ref}")


async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = db_execute("SELECT fpl_team_id FROM users WHERE telegram_id=?", (user.id,), fetchone=True)
    if not row:
        await update.message.reply_text("You haven't registered yet. Use /register <fpl_team_id>.")
        return
    gw = get_current_gameweek()
    entry = db_execute(
        "SELECT paid, tx_reference FROM entries WHERE telegram_id=? AND gameweek=?",
        (user.id, gw),
        fetchone=True,
    )
    status = "Not entered this gameweek yet."
    if entry:
        status = "✅ Payment confirmed, you're entered!" if entry[0] else "⏳ Waiting for payment to complete — check back in a minute after paying."
    await update.message.reply_text(f"FPL Team ID: {row[0]}\nGameweek {gw}: {status}")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw = get_current_gameweek()
    entries = db_execute(
        "SELECT u.telegram_id, u.username, u.fpl_team_id FROM entries e "
        "JOIN users u ON u.telegram_id = e.telegram_id WHERE e.gameweek=? AND e.paid=1",
        (gw,),
        fetch=True,
    )
    if not entries:
        await update.message.reply_text(f"No confirmed entries yet for GW{gw}.")
        return

    results = []
    for telegram_id, username, team_id in entries:
        score = get_gameweek_score(team_id, gw)
        results.append((username, score if score is not None else 0))
    results.sort(key=lambda x: x[1], reverse=True)

    lines = [f"📊 Gameweek {gw} Leaderboard:"]
    for i, (username, score) in enumerate(results, start=1):
        lines.append(f"{i}. {username} — {score} pts")
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------
async def announce_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Admins only.")
        return
    gw = get_current_gameweek() if not context.args else int(context.args[0])
    entries = db_execute(
        "SELECT u.telegram_id, u.username, u.fpl_team_id FROM entries e "
        "JOIN users u ON u.telegram_id = e.telegram_id WHERE e.gameweek=? AND e.paid=1",
        (gw,),
        fetch=True,
    )
    if not entries:
        await update.message.reply_text(f"No confirmed entries for GW{gw}.")
        return

    results = []
    for telegram_id, username, team_id in entries:
        score = get_gameweek_score(team_id, gw)
        results.append((username, telegram_id, score if score is not None else 0))
    results.sort(key=lambda x: x[2], reverse=True)

    winner_name, winner_id, winner_score = results[0]
    total_pot = len(entries) * ENTRY_FEE_BIRR
    prize = total_pot * 0.5

    text = (
        f"🏆 GW{gw} Winner: {winner_name} with {winner_score} points!\n"
        f"Pot: {total_pot} birr → Prize: {prize:.0f} birr (50%)"
    )
    await update.message.reply_text(text)
    await context.bot.send_message(winner_id, f"🎉 Congrats! You won GW{gw} with {winner_score} points. Prize: {prize:.0f} birr!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("mystatus", my_status))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("announcewinner", announce_winner))

    # Automatically checks Chapa for completed payments in the background —
    # this is what makes confirmation fully automatic, no admin needed.
    app.job_queue.run_repeating(check_pending_payments, interval=PAYMENT_CHECK_INTERVAL_SECONDS, first=10)

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
