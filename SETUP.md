# Setup

How to get the bot running.

## 1. Create the Discord application

1. Go to https://discord.com/developers/applications and click **New Application**.
2. Name it (e.g. "Roommate Bot") and create it.

## 2. Create the bot and get its token

1. In the left sidebar, open **Bot** and click **Add Bot**.
2. Click **Reset Token** and copy the token.
3. Copy `.env.example` to `.env` and set `BOT_TOKEN=your-token-here`.
   - Optional privileged intent: enable **Server Members Intent** under *Privileged Gateway Intents*. Not required, since the bot registers members as they interact.

## 3. Invite the bot to your server

1. Left sidebar → **OAuth2 → URL Generator**.
2. Scopes: check **`bot`** and **`applications.commands`** (required for slash commands).
3. Bot permissions: **Send Messages**, **Embed Links**, **Use Slash Commands**.
4. Copy the generated URL, open it in a browser, pick your server, and authorize.

## 4. Install and run

```bash
pip install -r requirements.txt
python bot.py
```

Notes:
- The bot must be running for slash commands to register (first run can take a few seconds to sync).
- Self-hosted locally, so it only works while the script is running on your machine.
- After first run, use `/setup channel:#general` to choose where reminders and statements are posted.
