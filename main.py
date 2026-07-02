from __future__ import annotations
import asyncio
import logging
import sys
import os
import time
from pyrogram import Client, idle
from pyrogram.errors import FloodWait, RPCError
from config import Config
from attack_engine import AttackEngine
from vc_detector import VCDetector
from bot_handler import BotHandler

# Try to use uvloop for better performance
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    LOGGER.info("✅ Using uvloop for better performance")
except ImportError:
    pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log")
    ]
)
LOGGER = logging.getLogger(__name__)

# Suppress noisy logs
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pyrogram.connection").setLevel(logging.WARNING)

async def amain():
    """Main async entry point"""
    max_retries = 3
    retry_delay = 10
    
    for attempt in range(max_retries):
        try:
            # Load config
            cfg = Config.from_env()
            LOGGER.info("✅ Configuration loaded")
            
            # Initialize clients
            bot = Client(
                "vc_bot",
                api_id=cfg.api_id,
                api_hash=cfg.api_hash,
                bot_token=cfg.bot_token,
                workdir="./sessions",
                sleep_threshold=60,
                max_concurrent_transmissions=10
            )
            
            user = Client(
                "vc_user",
                api_id=cfg.api_id,
                api_hash=cfg.api_hash,
                session_string=cfg.session_string,
                workdir="./sessions",
                sleep_threshold=60,
                max_concurrent_transmissions=10
            )
            
            # Start clients
            await bot.start()
            LOGGER.info("✅ Bot client started")
            
            await user.start()
            LOGGER.info("✅ User client started")
            
            # Check if bot is alive
            me = await bot.get_me()
            LOGGER.info(f"✅ Bot: @{me.username} (ID: {me.id})")
            
            # Initialize engine
            engine = AttackEngine(
                threads=cfg.max_threads,
                max_dur=cfg.max_duration,
                safety=False
            )
            
            # Initialize detector
            detector = VCDetector(user, cooldown=cfg.scan_cooldown)
            
            # Initialize handler
            handler = BotHandler(
                bot,
                detector,
                engine,
                cfg.admin_id,
                cfg.max_duration,
                cfg.scan_limit
            )
            
            LOGGER.info("🚀 **BOT IS LIVE!**")
            LOGGER.info("Commands: /scan, /attack, /nuke, /loop, /stop, /status")
            
            # Start idle
            await idle()
            
            # Cleanup
            LOGGER.info("Shutting down...")
            engine.stop()
            await detector.cleanup()
            await user.stop()
            await bot.stop()
            
            break  # Success
            
        except FloodWait as e:
            LOGGER.warning(f"FloodWait: {e.value}s")
            await asyncio.sleep(e.value + 5)
            
        except RPCError as e:
            LOGGER.error(f"RPC Error: {e}")
            if "SESSION_REVOKED" in str(e):
                LOGGER.critical("❌ Session expired! Update SESSION_STRING")
                break
                
            if attempt < max_retries - 1:
                LOGGER.info(f"Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
            else:
                raise
                
        except Exception as e:
            LOGGER.error(f"Error: {e}", exc_info=True)
            if attempt < max_retries - 1:
                LOGGER.info(f"Retrying in {retry_delay}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(retry_delay)
            else:
                raise

def main():
    """Main entry point"""
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        LOGGER.info("🛑 Shutdown by user")
    except Exception as e:
        LOGGER.critical(f"💀 Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
