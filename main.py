import asyncio
import logging
import os
import sys
from pyrogram import Client, idle, filters
from pyrogram.handlers import MessageHandler
from aiohttp import web

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger(__name__)

# Session folder
os.makedirs("./sessions", exist_ok=True)

def get_env(key, required=True, default=None):
    """Safe env variable getter"""
    value = os.getenv(key, default)
    if required and value is None:
        LOGGER.error(f"❌ {key} environment variable is missing!")
        sys.exit(1)
    return value

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    LOGGER.info(f"✅ Health server running on port {port}")
    
    while True:
        await asyncio.sleep(3600)

async def main():
    try:
        # SAFE ENV LOADING
        API_ID = get_env("API_ID")
        API_HASH = get_env("API_HASH")
        BOT_TOKEN = get_env("BOT_TOKEN")
        SESSION_STRING = get_env("SESSION_STRING", required=False)
        
        LOGGER.info("✅ Environment variables loaded")
        
        # Bot client
        bot = Client(
            "bot",
            api_id=int(API_ID),
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir="./sessions"
        )
        
        await bot.start()
        me = await bot.get_me()
        LOGGER.info(f"✅ Bot online: @{me.username} (ID: {me.id})")
        
        # User client
        if SESSION_STRING:
            user = Client(
                "user",
                api_id=int(API_ID),
                api_hash=API_HASH,
                session_string=SESSION_STRING,
                workdir="./sessions"
            )
            await user.start()
            LOGGER.info("✅ User client started")
        else:
            LOGGER.warning("⚠️ SESSION_STRING not set - VC detection disabled")
        
        # /start command
        @bot.on_message(filters.command("start"))
        async def start_handler(client, msg):
            await msg.reply(
                "🔥 **Bot is Alive!**\n\n"
                "Commands:\n"
                "/scan - Find VCs\n"
                "/attack <ip> <port> [duration]\n"
                "/nuke <ip:port> ... <duration>\n"
                "/loop <ip> <port> <duration> <iterations>\n"
                "/stop - Stop everything\n"
                "/status - Check status"
            )
        
        # /status command
        @bot.on_message(filters.command("status"))
        async def status_handler(client, msg):
            await msg.reply("✅ Bot is running normally!")
        
        LOGGER.info("🚀 BOT IS LIVE!")
        
        # Run both bot and health server
        await asyncio.gather(
            idle(),
            start_health_server()
        )
        
    except Exception as e:
        LOGGER.error(f"❌ Error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
