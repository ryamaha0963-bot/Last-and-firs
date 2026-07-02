from __future__ import annotations
import asyncio
import logging
import sys
import os
from pyrogram import Client, idle
from config import Config
from attack_engine import AttackEngine
from vc_detector import VCDetector
from bot_handler import BotHandler

# Session folder create karo
os.makedirs("./sessions", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
LOGGER = logging.getLogger(__name__)

# Pyrogram logs hatao
logging.getLogger("pyrogram").setLevel(logging.WARNING)

async def amain():
    try:
        cfg = Config.from_env()
        LOGGER.info("✅ Config loaded")
        
        # Bot client
        bot = Client(
            "vc_bot",
            api_id=cfg.api_id,
            api_hash=cfg.api_hash,
            bot_token=cfg.bot_token,
            workdir="./sessions",
            sleep_threshold=60
        )
        
        # User client
        user = Client(
            "vc_user",
            api_id=cfg.api_id,
            api_hash=cfg.api_hash,
            session_string=cfg.session_string,
            workdir="./sessions",
            sleep_threshold=60
        )
        
        # Start clients
        await bot.start()
        me = await bot.get_me()
        LOGGER.info(f"✅ Bot started: @{me.username}")
        
        await user.start()
        LOGGER.info("✅ User client started")
        
        # Init engine
        engine = AttackEngine(
            threads=cfg.max_threads,
            max_dur=cfg.max_duration
        )
        
        # Init detector
        detector = VCDetector(user, cooldown=cfg.scan_cooldown)
        
        # Init handler
        handler = BotHandler(
            bot, detector, engine,
            cfg.admin_id, cfg.max_duration, cfg.scan_limit
        )
        
        LOGGER.info("🚀 BOT IS LIVE!")
        LOGGER.info("Commands: /scan, /attack, /nuke, /loop, /stop, /status")
        
        # ⚠️ IMPORTANT: BAS IDLE - KOI HEALTH SERVER NAHI
        await idle()
        
        # Cleanup
        engine.stop()
        await detector.cleanup()
        await user.stop()
        await bot.stop()
        
    except Exception as e:
        LOGGER.error(f"Error: {e}", exc_info=True)
        raise

def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        LOGGER.info("🛑 Shutting down...")
    except Exception as e:
        LOGGER.critical(f"💀 Fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
