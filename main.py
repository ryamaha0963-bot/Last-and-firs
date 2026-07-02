from __future__ import annotations
import asyncio, logging, sys, os, time
from pyrogram import Client, idle
from pyrogram.errors import FloodWait, RPCError
from config import Config
from attack_engine import AttackEngine
from vc_detector import VCDetector
from bot_handler import BotHandler
import uvloop

# UVLoop for maximum performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
LOGGER = logging.getLogger(__name__)

# Simple web server for Railway health checks
async def health_server():
    try:
        from aiohttp import web
        app = web.Application()
        async def health(request):
            return web.Response(text="OK", status=200)
        app.router.add_get('/health', health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
        await site.start()
        LOGGER.info(f"✅ Health server running on port {os.environ.get('PORT', 8080)}")
        while True:
            await asyncio.sleep(60)
    except ImportError:
        LOGGER.warning("aiohttp not installed, skipping health server")
    except Exception as e:
        LOGGER.error(f"Health server error: {e}")

async def amain():
    # Retry logic for Railway
    max_retries = 5
    retry_delay = 10
    
    for attempt in range(max_retries):
        try:
            cfg = Config.from_env()
            
            # Initialize clients with timeout handling
            bot = Client(
                "vc_bot",
                api_id=cfg.api_id,
                api_hash=cfg.api_hash,
                bot_token=cfg.bot_token,
                workdir="./sessions",
                sleep_threshold=60
            )
            
            user = Client(
                "vc_user",
                api_id=cfg.api_id,
                api_hash=cfg.api_hash,
                session_string=cfg.session_string,
                workdir="./sessions",
                sleep_threshold=60
            )
            
            # Start clients with retry
            await bot.start()
            LOGGER.info("✅ Bot client started")
            await user.start()
            LOGGER.info("✅ User client started")
            
            engine = AttackEngine(
                threads=cfg.max_threads,
                max_dur=cfg.max_duration,
                safety=False
            )
            
            detector = VCDetector(user, cooldown=cfg.scan_cooldown)
            handler = BotHandler(
                bot, detector, engine, 
                cfg.admin_id, cfg.max_duration, cfg.scan_limit
            )
            
            LOGGER.info("🚀 Bot is LIVE on Railway!")
            LOGGER.info(f"Commands: /scan, /attack, /nuke, /loop, /stop")
            
            # Start health server
            asyncio.create_task(health_server())
            
            # Keep bot alive
            await idle()
            
            # Clean shutdown
            engine.stop()
            await user.stop()
            await bot.stop()
            break
            
        except FloodWait as e:
            LOGGER.warning(f"FloodWait: sleeping for {e.value}s")
            await asyncio.sleep(e.value + 5)
            
        except RPCError as e:
            LOGGER.error(f"RPC Error: {e}")
            if "SESSION_REVOKED" in str(e) or "SESSION_EXPIRED" in str(e):
                LOGGER.critical("Session expired! Update SESSION_STRING in Railway vars")
                break
            if attempt < max_retries - 1:
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
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        LOGGER.info("Shutting down...")
    except Exception as e:
        LOGGER.critical(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
