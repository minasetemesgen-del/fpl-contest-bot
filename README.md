# FPL Weekly Contest Bot — Fully Automatic Payments

No coding required, and no manual payment checking — everything confirms
itself. Follow these steps in order.

## 1. Create your bot on Telegram
- Open Telegram, search for **@BotFather**, start a chat.
- Send `/newbot`, give it a name and a username (must end in "bot", e.g. `MyFPLContestBot`).
- BotFather gives you a long **token** like `123456:ABC-DEF1234...`. Copy it.

## 2. Get your own Telegram ID
- Search for **@userinfobot**, start a chat, it instantly replies with your numeric ID.
- Copy that number too.

## 3. Set up Chapa (this is what makes payments automatic)
- Go to https://dashboard.chapa.co and create a free merchant account.
- You'll need to verify your identity/business details — this is Chapa's own
  KYC process, standard for any Ethiopian payment gateway.
- Once approved, go to **Settings → API Keys** and copy your **Secret Key**.
  Use the **Test** key first (starts with `CHASECK_TEST-`) to try everything
  without real money, then switch to the **Live** key when you're ready.
- Chapa handles Telebirr, CBE Birr, and card payments all through one link —
  you don't integrate with each one separately.

## 4. Set your environment variables
`config.py` reads everything from environment variables — nothing is
hardcoded in the code, which matters once this is on GitHub.

- `BOT_TOKEN` — from step 1
- `ADMIN_TELEGRAM_ID` — from step 2
- `CHAPA_SECRET_KEY` — from step 3
- `ENTRY_FEE_BIRR` — optional, defaults to 100
- `CHAPA_RETURN_URL` — optional, where users land after paying (defaults to a harmless placeholder)
- `PAYMENT_CHECK_INTERVAL_SECONDS` — optional, how often the bot checks for completed payments (defaults to 30)

**To test on your own computer**, run in your terminal before starting the bot:
```
export BOT_TOKEN="123456:ABC-your-real-token"
export ADMIN_TELEGRAM_ID="123456789"
export CHAPA_SECRET_KEY="CHASECK_TEST-your-key"
python bot.py
```

## 5. Deploy to Railway (recommended — free, no server management)

1. Create a free account at railway.com, sign in with GitHub.
2. Upload this whole `fpl_bot` folder to a new GitHub repository — you can do
   this straight from github.com (New repository → "uploading an existing
   file", drag and drop `bot.py`, `config.py`, `requirements.txt`), no
   command line needed.
3. In Railway: New Project → Deploy from GitHub repo → select that repo.
4. In your Railway project, go to the **Variables** tab and add `BOT_TOKEN`,
   `ADMIN_TELEGRAM_ID`, and `CHAPA_SECRET_KEY`.
5. Railway detects `requirements.txt`, installs everything, and runs `bot.py`
   automatically. Check the **Deploy Logs** tab — you should see "Bot
   starting..." with no errors.

## How it works now — zero manual steps

1. User runs `/register <their_fpl_team_id>`.
2. User runs `/pay` — the bot instantly generates a Chapa payment link and
   sends it. They tap it, pick Telebirr/CBE Birr/card, and pay.
3. In the background, the bot checks Chapa every 30 seconds for completed
   payments. The moment it sees one, it automatically marks that user as
   entered and messages them "✅ Payment confirmed automatically!" —
   **you never touch anything.**
4. Anytime, run `/leaderboard` to see live standings for the current gameweek.
5. After the gameweek ends (FPL scores usually finalize a day or two after
   the last match), run `/announcewinner` — the bot calculates the winner
   and the 50% prize automatically and messages everyone.

## Notes
- All data is stored in a file called `fpl_contest.db` that appears
  automatically — don't delete it, it's your whole user/payment/entry database.
- Chapa takes a small transaction fee per payment (check their current
  pricing on their dashboard) — factor that into your pot math if it matters to you.
- If you want a PS5/iPhone as the prize instead of cash on certain
  gameweeks, just announce that manually — the bot still tells you who won
  and by how much.
- Before taking real money from strangers, please check Ethiopia's rules
  around cash-prize contests (National Lottery Administration) — this is a
  business/legal step, not a coding one, but it protects you.
