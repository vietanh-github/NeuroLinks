# Developer Guide: NeuroLinks

## What This Does
NeuroLinks is a real-time system that collects links shared via a Telegram bot and displays them instantly on a web dashboard using Firebase. 

## Quick Setup

```bash
# Clone the repository
git clone https://github.com/vietanh-github/NeuroLinks.git
cd NeuroLinks

# Set up environment variables
cp .env.example .env
nano .env # Configure TELEGRAM_BOT_TOKEN, FIREBASE_PROJECT_ID, and ADMIN_ID

# Run development server (Docker)
docker compose up -d --build
```

## Key Files
- `bot/main.py` — Entry point for the Telegram bot
- `bot/handlers/link_handler.py` — Link processing, duplicate detection, and category saving
- `bot/handlers/admin_handler.py` — Admin panel and settings management
- `bot/firebase_client.py` — Wrapper for Firebase Admin SDK (database operations)
- `web/index.html` — The realtime vanilla JS/HTML frontend displaying the links

## How to Contribute
1. Fork or branch from main
2. Make changes to bot Python files or web HTML/CSS/JS
3. Open a PR — describe what and why

## Common Issues
- **Missing Firebase SDK Service Account JSON** → The bot will crash on startup if `neurolinks-4b8d9-firebase-adminsdk-fbsvc*.json` (or the file specified in `.env`) is missing.
- **Missing .env files** → Docker compose will fail to start if the `.env` file does not exist. Run `cp .env.example .env`. 
- **Bot doesn't respond to `/add` or messages** → Ensure your Telegram User ID is whitelisted by the admin using `/admin`. Only authorized users can interact with the bot.

## Who to Ask
- Viet Anh (Repository owner)
