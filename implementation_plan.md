# Telegram Link Collector → Website Realtime

Build a system where users send links to a Telegram bot → bot saves them to Firestore → website shows them in realtime using `onSnapshot`.

The system lives in the existing Firebase project directory at `/Users/vietanh/Downloads/Manual Library/FirebaseProject/linva.net/LinhNgon/`.

## User Review Required

> [!IMPORTANT]
> **Firebase credentials**: You'll need a Firebase Admin SDK service account JSON key for the Python bot backend. Do you already have this? If not, you'll need to download it from Firebase Console → Project Settings → Service Accounts.

> [!IMPORTANT]
> **Telegram Bot Token**: You need a bot token from [@BotFather](https://t.me/BotFather). Please confirm you have this ready, or I'll add setup instructions.

> [!IMPORTANT]
> **Frontend choice**: Plan uses **Next.js** (same stack as `dealhunter-app`). Should I use **Vanilla JS** (a single HTML file, no build step) instead for simplicity? This app is purely a viewer so either works.

---

## Proposed Changes

### Project Layout

```
LinhNgon/
├── bot/                        # Python Telegram bot
│   ├── main.py
│   ├── handlers/
│   │   └── link_handler.py
│   └── firebase_client.py
├── web/                        # Next.js frontend
│   ├── app/
│   │   ├── page.tsx
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── LinkCard.tsx
│   │   └── CategoryFilter.tsx
│   └── lib/
│       ├── firebase.ts
│       ├── types.ts
│       └── firestore.ts
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

### Backend — Python Bot

#### [NEW] `bot/main.py`
- Entry point using **aiogram 3.x** (async, modern)
- Registers handlers, starts polling

#### [NEW] `bot/handlers/link_handler.py`
- Handles any message containing a URL (regex match)
- Command: `/add <url> [category]` — explicit add
- Auto-detect: any raw URL pasted → prompt for category via inline keyboard
- Saves to Firestore collection `links` with schema:
  ```json
  {
    "url": "...",
    "category": "AI",
    "title": "",
    "description": "",
    "user_id": "123456789",
    "username": "@johndoe",
    "created_at": "<server_timestamp>"
  }
  ```
- Admin command: `/list` — shows last 10 links
- Admin command: `/delete <doc_id>` — deletes a link

#### [NEW] `bot/firebase_client.py`
- Initializes Firebase Admin SDK using service account JSON
- Provides `add_link()`, `get_links()`, `delete_link()` helpers

#### [NEW] `requirements.txt`
```
aiogram==3.x
firebase-admin
python-dotenv
```

#### [NEW] `.env.example`
```
TELEGRAM_BOT_TOKEN=your_token_here
FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json
FIREBASE_PROJECT_ID=your_project_id
```

---

### Frontend — Next.js

#### [NEW] `web/lib/types.ts`
```typescript
export interface Link {
  id: string;
  url: string;
  category: string;
  title: string;
  description: string;
  user_id: string;
  username: string;
  created_at: Timestamp;
}
```

#### [NEW] `web/lib/firebase.ts`
- Initializes Firebase client using `NEXT_PUBLIC_FIREBASE_*` env vars
- Same pattern as `dealhunter-app/lib/firebase.ts`

#### [NEW] `web/lib/firestore.ts`
- `subscribeToLinks(callback)` using `onSnapshot` for realtime
- `getLinks()` for SSR initial load
- Supports category filtering

#### [NEW] `web/app/page.tsx`
- Client component with `useEffect` + `onSnapshot` subscription
- `useState` for links list, loading state, selected category
- Renders `<LinkCard>` grid
- Shows "🔴 Live" indicator when realtime connection is active

#### [NEW] `web/components/LinkCard.tsx`
- Displays: favicon, URL (truncated), category badge, date, username
- Hover → link opens in new tab
- Glassmorphism card style

#### [NEW] `web/components/CategoryFilter.tsx`
- Pill-style filter buttons for each unique category
- "All" selected by default

#### [NEW] `web/app/globals.css`
- Dark mode design system (similar to dealhunter aesthetic)
- Custom `--brand-*` CSS variables

---

### DevOps

#### [NEW] `Dockerfile`
- Multi-stage: Python 3.12-slim
- Runs `bot/main.py`

#### [NEW] `docker-compose.yml`
- Service: `bot` (Python)
- Env file: `.env`

#### [NEW] `README.md`
- Full setup guide: Firebase project, service account, bot token, running locally, deploying

---

## Verification Plan

### Automated Tests
- None planned (the system is I/O heavy — Telegram API + Firestore). Integration testing via manual flow below.

### Manual Verification

**Step 1 — Bot sends link to Firestore:**
1. `cd LinhNgon && pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and fill in real values
3. `python bot/main.py`
4. Open Telegram, send `/add https://openai.com AI` to the bot
5. Check Firebase Console → Firestore → `links` collection → confirm document appears

**Step 2 — Website shows realtime updates:**
1. `cd web && npm install && npm run dev`
2. Open `http://localhost:3000` in browser
3. From Telegram: send another link `/add https://huggingface.co ML`
4. Without refreshing the browser, confirm the new link appears on the page within ~2 seconds

**Step 3 — Category filter:**
1. Send links with different categories (AI, ML, Tools)
2. Click each category pill on the website → confirm correct filtering

**Step 4 — Edge cases:**
1. Send a message without a URL → bot should ignore or reply "No URL detected"
2. Send a duplicate URL → currently allowed (no dedup), just creates another document
