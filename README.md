# PediaBot

Automated daily pediatric Telegram post for **@LaythPeds**.

## What it does
- Runs daily at **20:00 Qatar time (17:00 UTC)** using GitHub Actions.
- Pulls pediatric/health updates from public RSS feeds.
- Posts source links plus a pediatric clinical MCQ.
- Can be run manually from **Actions → Daily Pediatrics Telegram → Run workflow**.

## Required secret
In GitHub open:

**Settings → Secrets and variables → Actions → New repository secret**

Name: `TELEGRAM_BOT_TOKEN`

Value: your Telegram bot token.

Never commit the bot token to this repository.
