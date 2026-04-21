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

# 1. Configuration & Secrets
# On Render, manually add these to the 'Environment' tab in the dashboard
load_dotenv("config.env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_raw_users = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USERS = {int(i.strip()) for i in _raw_users.split(",") if i.strip().isdigit()}

CF_TOKEN = os.getenv("CF_API_TOKEN")
CF_ZONE = os.getenv("CF_ZONE_ID")
DNS_RECORDS = {
    "Subdomain 1": os.getenv("CF_RECORD_ID_1"),
    "Subdomain 2": os.getenv("CF_RECORD_ID_2"),
}

# 2. Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 3. Flask Heartbeat (To keep Render Web Service alive)
server = Flask('')

@server.route('/')
def home():
    return "DNS Bot is active and healthy."

def run_flask():
    # Render assigns a port dynamically via the PORT env var
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

def start_heartbeat():
    """Starts the web server in a separate background thread."""
    t = Thread(target=run_flask)
    t.daemon = True 
    t.start()

# 4. DNS Logic
async def update_cloudflare_dns(new_ip: str) -> list:
    """Asynchronously patches Cloudflare DNS records."""
    url_base = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/dns_records"
    headers = {
        "Authorization": f"Bearer {CF_TOKEN}",
        "Content-Type": "application/json",
    }
    
    results = []
    async with httpx.AsyncClient() as client:
        for label, rec_id in DNS_RECORDS.items():
            if not rec_id:
                results.append(f"❌ {label}: Missing Record ID")
                continue
                
            payload = {"type": "A", "content": new_ip, "ttl": 1, "proxied": False}
            
            try:
                resp = await client.patch(f"{url_base}/{rec_id}", headers=headers, json=payload)
                if resp.status_code == 200:
                    results.append(f"✅ {label}: Updated")
                else:
                    results.append(f"❌ {label}: API Error {resp.status_code}")
            except Exception as e:
                logger.error(f"Failed to update {label}: {e}")
                results.append(f"❌ {label}: Connection Error")
                
    return results

# 5. Telegram Handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt by ID: {user_id}")
        return

    text = update.message.text.strip()
    
    try:
        ip_obj = ipaddress.ip_address(text)
        status_msg = await update.message.reply_text(f"⏳ Updating DNS to {ip_obj}...")
        
        update_results = await update_cloudflare_dns(str(ip_obj))
        
        report = "\n".join(update_results)
        await status_msg.edit_text(f"Update Report:\n{report}")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid Input. Please send a valid IP address.")

# 6. Modern Async Entry Point
async def run_bot():
    if not TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found. Check your environment variables.")
        return

    # Start the Flask server so Render doesn't shut us down
    start_heartbeat()

    # Build the Application
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Using the async context manager ensures proper startup and shutdown
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        
        logger.info("Bot is successfully polling in Async mode.")
        
        # Keep the loop running until the process is terminated
        stop_event = asyncio.Event()
        await stop_event.wait()

if __name__ == "__main__":
    try:
        # asyncio.run handles loop creation for Python 3.11+
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested.")
