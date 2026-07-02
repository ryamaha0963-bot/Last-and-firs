import asyncio
import logging
import os
from pyrogram import Client, idle, filters
from pyrogram.handlers import MessageHandler

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# Session folder
os.makedirs("./sessions", exist_ok=True)

async def main():
    try:
        # Config se load
        API_ID = int(os.getenv("API_ID"))
        API_HASH = os.getenv("API_HASH")
        BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        # Bot client - SIRF BOT (user client nahi)
        bot = Client(
            "bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir="./sessions"
        )
        
        # Start bot
        await bot.start()
        me = await bot.get_me()
        LOGGER.info(f"✅ BOT ONLINE: @{me.username}")
        
        # /start command
        async def start_handler(client, msg):
            await msg.reply("🔥 Bot is alive! /scan, /attack, /nuke, /loop, /stop")
        
        bot.add_handler(MessageHandler(start_handler, filters.command("start")))
        
        # Status command
        async def status_handler(client, msg):
            await msg.reply("✅ Bot is running!")
        
        bot.add_handler(MessageHandler(status_handler, filters.command("status")))
        
        LOGGER.info("🚀 BOT READY! Send /start to test")
        
        # ⚠️ BAS IDLE - KOI HEALTH CHECK NAHI
        await idle()
        
        await bot.stop()
        LOGGER.info("🛑 Bot stopped")
        
    except Exception as e:
        LOGGER.error(f"Error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
