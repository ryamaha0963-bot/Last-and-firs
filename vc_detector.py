from __future__ import annotations
import asyncio, json, logging, re, time, socket, ipaddress
from dataclasses import dataclass
from pyrogram import Client
from pyrogram.errors import FloodWait, ChatAdminRequired, UserAlreadyParticipant, RPCError
from pyrogram.raw import functions, types
from utils import IPV4_RE

LOGGER = logging.getLogger(__name__)

@dataclass
class VCRecord:
    dialog_id: int
    title: str
    peer: any
    call: any
    chat_id: int

class VCDetector:
    def __init__(self, client: Client, cooldown: int = 5):
        self.client = client
        self.cooldown = cooldown
        self._last = 0.0
        self._joined_calls = set()

    async def scan(self, limit: int = 50) -> list[VCRecord]:
        """Scan dialogs for active voice chats"""
        now = time.time()
        if now - self._last < self.cooldown:
            await asyncio.sleep(self.cooldown - (now - self._last))
        self._last = time.time()
        
        results = []
        try:
            async for dialog in self.client.get_dialogs(limit=limit):
                chat = dialog.chat
                if not chat:
                    continue
                    
                try:
                    peer = await self.client.resolve_peer(chat.id)
                    call = await self._get_call(peer)
                    
                    if call:
                        results.append(VCRecord(
                            chat.id,
                            chat.title or str(chat.id),
                            peer,
                            call,
                            chat.id
                        ))
                        LOGGER.info(f"✅ Found VC: {chat.title}")
                        
                except FloodWait as e:
                    LOGGER.warning(f"FloodWait: {e.value}s")
                    await asyncio.sleep(e.value + 1)
                except Exception as e:
                    LOGGER.debug(f"Scan error for {chat.id}: {e}")
                    continue
                    
        except Exception as e:
            LOGGER.error(f"Scan failed: {e}")
            
        return results

    async def _get_call(self, peer):
        """Get active call from peer"""
        try:
            if isinstance(peer, types.InputPeerChannel):
                full = await self.client.invoke(
                    functions.channels.GetFullChannel(
                        channel=types.InputChannel(peer.channel_id, peer.access_hash)
                    )
                )
                return getattr(full.full_chat, "call", None)
                
            elif isinstance(peer, types.InputPeerChat):
                full = await self.client.invoke(
                    functions.messages.GetFullChat(chat_id=peer.chat_id)
                )
                return getattr(full.full_chat, "call", None)
                
            elif isinstance(peer, types.InputPeerUser):
                # Users can't have VCs
                return None
                
        except Exception as e:
            LOGGER.debug(f"Get call error: {e}")
            
        return None

    async def extract(self, record: VCRecord) -> dict:
        """Extract IPs from voice chat - AGGRESSIVE extraction"""
        joined = False
        notice = None
        parsed = {}
        ips = set()
        
        # Try multiple approaches to join
        for attempt in range(3):
            try:
                me = await self.client.resolve_peer('me')
                
                # Try to get call params
                call_params = getattr(record.call, "params", None)
                if not call_params:
                    # Fallback params
                    call_params = types.DataJSON(
                        data=json.dumps({
                            "ufrag": "x",
                            "pwd": "y",
                            "fingerprints": [],
                            "ssrc": 1
                        })
                    )
                    notice = "Using fallback params"
                
                # Join the call
                await self.client.invoke(
                    functions.phone.JoinGroupCall(
                        call=types.InputGroupCall(
                            record.call.id,
                            record.call.access_hash
                        ),
                        join_as=me,
                        params=call_params,
                        muted=True,
                        video_stopped=True
                    )
                )
                joined = True
                self._joined_calls.add(record.call.id)
                await asyncio.sleep(1.0)
                break
                
            except UserAlreadyParticipant:
                joined = True
                self._joined_calls.add(record.call.id)
                break
                
            except FloodWait as e:
                LOGGER.warning(f"FloodWait: {e.value}s")
                await asyncio.sleep(e.value + 1)
                
            except Exception as e:
                notice = f"Join attempt {attempt+1} failed: {e}"
                await asyncio.sleep(0.5)

        # Extract call info - MULTIPLE METHODS
        try:
            # Method 1: GetGroupCall
            group = await self.client.invoke(
                functions.phone.GetGroupCall(
                    call=types.InputGroupCall(
                        record.call.id,
                        record.call.access_hash
                    ),
                    limit=200
                )
            )
            
            call_obj = group.call
            raw = getattr(call_obj, "params", None)
            
            if raw:
                data = getattr(raw, "data", "{}")
                try:
                    parsed = json.loads(data) if data else {}
                except:
                    parsed = {}
            
            # Extract from raw data
            all_text = json.dumps(parsed) + str(record.call) + str(group)
            
        except Exception as e:
            notice = (notice or "") + f" GetGroupCall error: {e}"
            all_text = str(record.call)

        # Method 2: Regex IP extraction
        for ip in IPV4_RE.findall(all_text):
            if ip and not ip.startswith("0.") and not ip.startswith("127."):
                ips.add(ip)

        # Method 3: Extract from endpoints
        for ep in parsed.get("endpoints", []):
            if isinstance(ep, str):
                if ":" in ep:
                    parts = ep.rsplit(":", 1)
                    if len(parts) == 2 and parts[0].replace('.', '').isdigit():
                        ips.add(parts[0])
            elif isinstance(ep, dict):
                ip = ep.get("ip") or ep.get("host") or ep.get("address")
                if ip and isinstance(ip, str):
                    ips.add(ip)

        # Method 4: Extract from servers
        for srv in parsed.get("servers", []):
            if isinstance(srv, dict):
                ip = srv.get("ip") or srv.get("host") or srv.get("address")
                if ip and isinstance(ip, str):
                    ips.add(ip)
                port = srv.get("port", 0)
            elif isinstance(srv, str):
                if ":" in srv:
                    parts = srv.rsplit(":", 1)
                    if len(parts) == 2:
                        ips.add(parts[0])

        # Method 5: Extract from ICE candidates
        for key in ["candidates", "ice", "turn", "stun"]:
            if key in parsed:
                data = parsed[key]
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            ip = item.get("ip") or item.get("host") or item.get("address")
                            if ip and isinstance(ip, str):
                                ips.add(ip)
                        elif isinstance(item, str):
                            if ":" in item:
                                parts = item.rsplit(":", 1)
                                if len(parts) == 2 and parts[0].replace('.', '').isdigit():
                                    ips.add(parts[0])

        # Filter and format IPs
        ip_list = []
        for ip in ips:
            if ip and not ip.startswith("0.") and not ip.startswith("127."):
                # Try to find port from parsed data
                port = 10001  # Default
                for ep in parsed.get("endpoints", []):
                    if isinstance(ep, dict) and ep.get("ip") == ip:
                        port = ep.get("port", 10001)
                        break
                
                ip_list.append({
                    "ip": ip,
                    "port": port,
                    "type": "auto",
                    "region": "unknown",
                    "source": "extracted"
                })

        # If no IPs found, try alternative method
        if not ip_list:
            # Try to get from call participants
            try:
                participants = await self.client.invoke(
                    functions.phone.GetGroupCall(
                        call=types.InputGroupCall(
                            record.call.id,
                            record.call.access_hash
                        ),
                        limit=200
                    )
                )
                for p in participants.participants:
                    if hasattr(p, "source"):
                        # Extract from participant source
                        source_data = str(p)
                        for ip in IPV4_RE.findall(source_data):
                            if ip and not ip.startswith("0.") and not ip.startswith("127."):
                                ip_list.append({
                                    "ip": ip,
                                    "port": 10001,
                                    "type": "participant",
                                    "region": "unknown",
                                    "source": "participant"
                                })
            except:
                pass

        return {
            "title": record.title,
            "call_id": record.call.id,
            "chat_id": record.chat_id,
            "joined": joined,
            "notice": notice,
            "extracted_ips": ip_list,
            "participants": len(getattr(group, "participants", [])) if 'group' in locals() else 0,
            "raw_data": parsed
        }

    async def leave(self, record: VCRecord):
        """Leave voice chat"""
        try:
            if record.call.id in self._joined_calls:
                await self.client.invoke(
                    functions.phone.LeaveGroupCall(
                        call=types.InputGroupCall(
                            record.call.id,
                            record.call.access_hash
                        ),
                        source=0
                    )
                )
                self._joined_calls.remove(record.call.id)
                LOGGER.info(f"Left VC: {record.title}")
        except Exception as e:
            LOGGER.debug(f"Leave error: {e}")

    async def cleanup(self):
        """Cleanup all joined calls"""
        for call_id in list(self._joined_calls):
            try:
                await self.client.invoke(
                    functions.phone.LeaveGroupCall(
                        call=types.InputGroupCall(call_id, 0),
                        source=0
                    )
                )
            except:
                pass
        self._joined_calls.clear()
