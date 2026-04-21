import os
import asyncio
import logging
import ipaddress
import httpx
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 1. Load config
load_dotenv("config.env")

# 2. Flask Heartbeat (To keep Render happy)
server = Flask('')
@server.route('/')
def home():
    return "Bot is running!"

def run_flask():
    # Render provides the PORT env var; default to 8080
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True # Ensure thread dies when main script dies
    t.start()

# 3. Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 4. Env Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_raw_users = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USERS = {int(i.strip()) for i in _raw_users.split(",") if i.strip().isdigit()}
CF_TOKEN = os.getenv("CF_API_TOKEN")
CF_ZONE = os.getenv("CF_ZONE_ID")
DNS_RECORDS = {
    "Record 1": os.getenv("CF_RECORD_ID_1"),
    "Record 2": os.getenv("CF_RECORD_ID_2"),
}

async def update_dns(new_ip: str) -> list:
    url_base = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/dns_records"
    headers = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}
    results = []
    async with httpx.AsyncClient() as client:
        for label, rec_id in DNS_RECORDS.items():
            if not rec_id: continue
            try:
                resp = await client.patch(f"{url_base}/{rec_id}", headers=headers, 
                                          json={"type": "A", "content": new_ip, "ttl": 1})
                results.append(f"✅ {label}: Updated" if resp.status_code == 200 else f"❌ {label}: Failed")
            except Exception:
                results.append(f"❌ {label}: Error")
    return results

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    text = update.message.text.strip()
    try:
        ipaddress.ip_address(text)
        status_msg = await update.message.reply_text("🔄 Updating DNS...")
        results = await update_dns(text)
        await status_msg.edit_text(f"Report for {text}:\n" + "\n".join(results))
    except ValueError:
        await update.message.reply_text("Invalid IP format.")

def main():
    if not TOKEN:
        print("Missing TELEGRAM_BOT_TOKEN")
        return

    # Start the Flask web server in a background thread
    keep_alive()

    # Build the bot
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is starting...")
    
    # run_polling() is the standard way, but we must ensure 
    # it's called correctly in the MainThread
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
