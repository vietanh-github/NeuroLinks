# NeuroLinks 🔗

**Telegram bot → Firebase Firestore → Realtime website.**

Users send links to the Telegram bot. Links are saved to Firestore. The website shows them live using `onSnapshot`.

---

## 📁 Project structure

```
NeuroLinks/
├── bot/
│   ├── main.py                  # Bot entry point (aiogram 3.x)
│   ├── firebase_client.py       # Firestore helpers
│   └── handlers/
│       ├── link_handler.py      # URL detection + /add command
│       └── admin_handler.py     # Admin commands
├── web/
│   └── index.html               # Realtime viewer (open directly in browser)
├── requirements.txt
├── .env                         # ← your secrets (not committed)
├── .env.example                 # template
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## ⚙️ Setup

### 1. Firebase — Backend (Admin SDK)
Already done: `neurolinks-4b8d9-firebase-adminsdk-fbsvc-180872d1e2.json` is in this directory.

Set Firestore rules to allow reads (for the website):

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Public read for links and settings
    match /links/{doc}   { allow read: if true; allow write: if false; }
    match /settings/{doc} { allow read: if true; allow write: if false; }
  }
}
```

### 2. Firebase — Frontend (Web App config)

1. Go to [Firebase Console](https://console.firebase.google.com/) → Project `neurolinks-4b8d9`
2. **Project Settings** → **General** → scroll to **Your apps**
3. Click **Add app** → Web (if not already created)
4. Copy the `firebaseConfig` object
5. Open `web/index.html` and replace the placeholder `firebaseConfig` values

### 3. Start the bot (local)

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python bot/main.py
```

### 4. Open the website

Simply open `web/index.html` in your browser — no build step needed.

---

## 🤖 Bot commands

### User commands (whitelisted users only)
| Command | Description |
|---------|-------------|
| Paste any URL | Auto-detect, ask for category |
| `/add <url> [category]` | Add link directly |
| `/help` | Show commands |

### Admin commands (ADMIN_ID only)
| Command | Description |
|---------|-------------|
| `/list` | Show last 10 links |
| `/delete <doc_id>` | Delete a link |
| `/categories` | List categories |
| `/addcategory <name>` | Add a category |
| `/removecategory <name>` | Remove a category |
| `/users` | List whitelisted users |
| `/adduser <user_id>` | Add user to whitelist |
| `/removeuser <user_id>` | Remove user from whitelist |

---

## 🐳 Deploy with Docker

```bash
docker compose up -d --build
```

---

## 🔥 Firestore schema

### `links/{doc_id}`
```json
{
  "url": "https://openai.com",
  "category": "AI",
  "user_id": "123456789",
  "username": "@johndoe",
  "created_at": "<server timestamp>"
}
```

### `settings/main`
```json
{
  "categories": ["AI", "ML", "Tools", "News", "Other"],
  "allowed_user_ids": [111111111, 222222222]
}
```
