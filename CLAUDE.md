# NeuroLinks — Project Configuration

## Overview
NeuroLinks is a real-time Telegram-to-Firestore link collector with a dark glassmorphism web viewer powered by Vanilla HTML and JS.

## Tech Stack
- Framework: aiogram 3.x (Bot), Vanilla HTML/JS (Frontend)
- Language: Python, JavaScript
- Package Manager: pip
- Test Framework: none
- Build Tool: Docker, Firebase CLI
- Linter: none
- Python Environment: none

## Directory Structure
- `bot/` — Python bot source code (main.py, handlers, firebase_client)
- `web/` — Frontend web app (index.html, CSS, JS)
- `Dockerfile` & `docker-compose.yml` — Containerization 
- `deploy.sh` — Deployment script for Firebase hosting

## Conventions
- Naming: `snake_case` for Python functions and variables (`cmd_start`, `add_link`), `camelCase` for JS functions
- Error handling: manual try/except around API calls, error boundaries shown via Telegram bot replies
- State management: `MemoryStorage` in aiogram (FSMContext) for bot state, Firebase Firestore for data (realtime `onSnapshot`)
- API pattern: Firebase Admin SDK (Python), Firebase JS SDK v11 (Frontend)
- Test structure: none

## Commands
- Install: `pip install -r requirements.txt`
- Dev: `python3 bot/main.py`
- Build: `docker compose up -d --build`
- Test: none
- Lint: none

## Key Files
- Entry point: `bot/main.py`
- Frontend: `web/index.html`
- Config: `docker-compose.yml`, `firebase.json`
- Routes/API: `bot/handlers/link_handler.py`, `bot/firebase_client.py`
