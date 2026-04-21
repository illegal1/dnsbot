import os
import logging
import ipaddress
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 1. Load configuration from specific env file
load_dotenv("config.env")

# 2. Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 3. Environment Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_raw_users = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USERS = {int(i.strip()) for i in _raw_users.split(",") if i.strip().isdigit()}

CF_TOKEN = os.getenv("CF_API_TOKEN")
CF_ZONE = os.getenv("CF_ZONE_ID")
# Dictionary mapping for easy iteration
DNS_RECORDS = {
    "Record 1": os.getenv("CF_RECORD_ID_1"),
    "Record 2": os.getenv("CF_RECORD_ID_2"),
}

async def update_dns(new_ip: str) -> list:
    """Updates both DNS records in Cloudflare."""
    url_base = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/dns_records"
    headers = {
        "Authorization": f"Bearer {CF_TOKEN}",
        "Content-Type": "application/json",
    }
    
    results = []
    async with httpx.AsyncClient() as client:
        for label, rec_id in DNS_RECORDS.items():
            if not rec_id:
                results.append(f"❌ {label}: Missing ID in config")
                continue
                
            payload = {
                "type": "A",
                "content": new_ip,
                "ttl": 1, # '1' means Automatic TTL
                "proxied": False
            }
            
            try:
                # Use PATCH or PUT; PATCH only updates specified fields
                resp = await client.patch(f"{url_base}/{rec_id}", headers=headers, json=payload)
                if resp.status_code == 200:
                    results.append(f"✅ {label}: Updated")
                else:
                    results.append(f"❌ {label}: API Error ({resp.status_code})")
            except Exception as e:
                results.append(f"❌ {label}: Connection Error")
                logger.error(f"DNS Update Error: {e}")
                
    return results

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main logic for processing messages."""
    user_id = update.effective_user.id
    
    # Security: Verify User
    if user_id not in ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt by ID: {user_id}")
        return

    text = update.message.text.strip()
    
    # Validation: Verify IP Format
    try:
        ipaddress.ip_address(text)
    except ValueError:
        await update.message.reply_text("Invalid input. Please send a valid IPv4 address.")
        return

    # Action
    status_msg = await update.message.reply_text("🔄 Processing DNS update...")
    update_results = await update_dns(text)
    
    # Final Response
    response_text = "\n".join(update_results)
    await status_msg.edit_text(f"Update Report for {text}:\n\n{response_text}")

def main():
    if not TOKEN or not CF_TOKEN:
        print("Error: Missing critical tokens in config.env")
        return

    # Create the application
    app = Application.builder().token(TOKEN).build()

    # Handle all text messages (that aren't commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()