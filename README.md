# PediaBot Production

This version does **not** use a finite repeating MCQ bank.

## How it works
At 20:00 Qatar, it retrieves recent pediatric evidence from PubMed and uses Gemini to create exactly two new resident-level case MCQs. It checks new stems against up to 2,000 prior questions and rejects semantic/text similarity above the configured threshold. It rotates through 16 pediatric domains. The exact generated questions, answers, and evidence are persisted to `data/state.json` by GitHub Actions.

At 22:00 Qatar, it reads the persisted questions from that same date, so the answer reveal cannot drift from the polls.

If question generation cannot produce two validated unique questions, the workflow fails instead of posting recycled/fabricated questions.

## Required GitHub secrets
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`

Gemini API has a Free Tier for eligible projects; create the API key in Google AI Studio. No Replit/Railway/server is required.

## Manual test
Actions → PediaBot Production → Run workflow → `brief`.
After it succeeds, run `reveal`.

## Persistence
Workflow permission is `contents: write` so GitHub Actions can commit `data/state.json`. This is required for long-term deduplication and exact brief/reveal matching.

## Evidence safety
Evidence candidates come from PubMed E-utilities. The model is instructed to summarize only the supplied title/abstract. Each item links to its PubMed record. If a supported summary cannot be produced, filler is omitted.
