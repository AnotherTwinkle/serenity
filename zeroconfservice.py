import asyncio
import socket
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from zeroconf import IPVersion, ServiceInfo, ServiceListener
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser, AsyncServiceInfo

logger = logging.getLogger(__name__)

@dataclass
class DiscoveredHost:
    """Represents a discovered Serenity node on the local network."""
    name: str                                   # e.g., "node-102030._serenity._tcp.local."
    addresses: List[str]                        # List of IP strings (IPv4/IPv6)
    port: int                                   # Target HTTP/WSS gateway port
    server: str                                 # Hostname (e.g., "termux.local.")
    properties: Dict[str, str]                  # Metadata TXT records (uid, platform, version)
    discovered_at: float = field(default_factory=time.time)
    sent_hello : bool = False

    @property
    def primary_ip(self) -> Optional[str]:
        return self.addresses[0] if self.addresses else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ip": self.primary_ip,
            "addresses": self.addresses,
            "port": self.port,
            "server": self.server,
            "properties": self.properties,
            "discovered_at": self.discovered_at,
        }

class SerenityServiceListener(ServiceListener):
    def __init__(self, service: "ZeroconfService"):
        super().__init__()
        self.service = service
        self.loop = asyncio.get_running_loop()

    def _schedule(self, coro) -> None:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        fut.add_done_callback(self._on_future_done)

    def _on_future_done(self, fut: asyncio.Future) -> None:
        try:
            fut.result()
        except Exception as e:
            logger.exception(f"Unhandled exception in Zeroconf listener: {e}")

    def add_service(self, zc, type_: str, name: str) -> None:
        self._schedule(self.service._on_service_added(zc, type_, name))

    def update_service(self, zc, type_: str, name: str) -> None:
        self._schedule(self.service._on_service_updated(zc, type_, name))

    def remove_service(self, zc, type_: str, name: str) -> None:
        self._schedule(self.service._on_service_removed(type_, name))


class ZeroconfService:
    SERVICE_TYPE = "_serenity._tcp.local."

    def __init__(self, node: Any, port: int = 2406, health_check_interval: float = 10.0):
        self.node = node
        self.port = port
        self.health_check_interval = health_check_interval

        self.aiozeroconf: Optional[AsyncZeroconf] = None
        self.browser: Optional[AsyncServiceBrowser] = None
        self.local_info: Optional[ServiceInfo] = None
        self._health_check_task: Optional[asyncio.Task] = None

        self._hosts: Dict[str, DiscoveredHost] = {}

    async def start(self) -> None:
        self.aiozeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self._register_advertisement()
        
        listener = SerenityServiceListener(self)
        self.browser = AsyncServiceBrowser(
            self.aiozeroconf.zeroconf, 
            self.SERVICE_TYPE, 
            listener=listener
        )
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info(f"Service operational. Advertising on {self.SERVICE_TYPE}")

    async def stop(self) -> None:
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self.browser:
            await self.browser.async_cancel()

        if self.aiozeroconf and self.local_info:
            await self.aiozeroconf.async_unregister_service(self.local_info)
            await self.aiozeroconf.async_close()

    def get_hosts(self) -> List[DiscoveredHost]:
        return list(self._hosts.values())

    def get_host(self, name: str) -> Optional[DiscoveredHost]:
        return self._hosts.get(name)

    async def resolve_host_by_uid(self, uid: str, timeout: float = 3.0) -> Optional[DiscoveredHost]:
        """Actively resolves a host via mDNS if not in background cache (solves race conditions)."""
        # Fast path: already known
        for host in self._hosts.values():
            if host.properties.get('uid') == uid:
                return host

        # Slow path: Actively query network using predictable instance name
        if not self.aiozeroconf:
            return None

        instance_name = f"{uid}.{self.SERVICE_TYPE}"
        info = AsyncServiceInfo(self.SERVICE_TYPE, instance_name)
        
        logger.debug(f"Actively querying mDNS for {instance_name}...")
        if await info.async_request(self.aiozeroconf.zeroconf, int(timeout * 1000)):
            return self._update_host_record(instance_name, info)
            
        return None

    async def force_refresh(self) -> None:
        if not self.aiozeroconf:
            return
        
        logger.info("Manual refresh requested. Querying network...")
        for name in list(self._hosts.keys()):
            info = AsyncServiceInfo(self.SERVICE_TYPE, name)
            if await info.async_request(self.aiozeroconf.zeroconf, timeout=3000):
                self._update_host_record(name, info)

    async def _health_check_loop(self) -> None:
        """Periodically tests TCP reachability using concurrent probing."""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                current_hosts = list(self._hosts.values())
                
                async def check_and_remove(host):
                    is_alive = await self._probe_host(host)
                    if not is_alive:
                        logger.warning(f"Node {host.name} failed health check (unannounced offline). Removing...")
                        await self._on_service_removed(self.SERVICE_TYPE, host.name)

                # Probing all hosts concurrently saves massive amounts of time 
                # if multiple nodes abruptly drop offline.
                if current_hosts:
                    await asyncio.gather(*(check_and_remove(h) for h in current_hosts))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in Zeroconf health check loop: {e}")

    async def _probe_host(self, host: DiscoveredHost, timeout: float = 2.0) -> bool:
        if not host.primary_ip:
            return False
        
        for ip in host.addresses:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, host.port),
                    timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (OSError, asyncio.TimeoutError):
                continue
        return False

    async def _on_service_added(self, zc: Any, type_: str, name: str) -> None:
        if self.local_info and name == self.local_info.name:
            return

        info = AsyncServiceInfo(type_, name)
        if await info.async_request(zc, timeout=3000):
            is_new = name not in self._hosts
            host = self._update_host_record(name, info)
            
            if is_new:
                logger.info(f"Discovered node: {name} ({host.primary_ip}:{host.port})")
                await self.node.events.dispatch("node_discovered", host=host)

    async def _on_service_updated(self, zc: Any, type_: str, name: str) -> None:
        if self.local_info and name == self.local_info.name:
            return

        info = AsyncServiceInfo(type_, name)
        if await info.async_request(zc, timeout=3000):
            was_offline = name not in self._hosts
            host = self._update_host_record(name, info)
            
            if was_offline:
                logger.info(f"Node re-discovered via update: {name} ({host.primary_ip}:{host.port})")
                await self.node.events.dispatch("node_discovered", host=host)
            else:
                logger.info(f"Host metadata updated: {name}")
                await self.node.events.dispatch("node_updated", host=host)

    async def _on_service_removed(self, type_: str, name: str) -> None:
        removed_host = self._hosts.pop(name, None)
        self._purge_zeroconf_cache(name)

        if removed_host:
            logger.info(f"Node offline: {name}")
            await self.node.events.dispatch("node_lost", host=removed_host)

    def _purge_zeroconf_cache(self, name: str) -> None:
        """Safely resets ServiceBrowser tracking without crashing zeroconf DNS cache."""
        if not self.browser:
            return
        
        services = getattr(self.browser, "services", getattr(self.browser, "_services", None))
        if isinstance(services, dict):
            services.pop(name, None)
        elif isinstance(services, set):
            services.discard(name)

    def _update_host_record(self, name: str, info: AsyncServiceInfo) -> DiscoveredHost:
        addresses = [str(ip) for ip in info.parsed_addresses()]
        
        properties = {}
        for k, v in info.properties.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            val = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            properties[key] = val

        host = DiscoveredHost(
            name=name,
            addresses=addresses,
            port=info.port,
            server=info.server,
            properties=properties
        )
        self._hosts[name] = host
        return host

    async def _register_advertisement(self) -> None:
        local_ip = self._detect_local_ip()
        node_uid = self.node.config.get("uid", "serenity-node-default")
        platform_name = self.node.config.get("platform", "unknown")

        instance_name = f"{node_uid}.{self.SERVICE_TYPE}"
        server_hostname = f"{node_uid}.local."

        properties = {
            "uid": node_uid,
            "version": "1.0.0",
            "platform": platform_name,
            "connection_modes": "rest-p2p"
        }

        self.local_info = ServiceInfo(
            self.SERVICE_TYPE,
            instance_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties=properties,
            server=server_hostname
        )

        logger.info(f"Registering local presence: {local_ip}:{self.port} as '{instance_name}'")
        await self.aiozeroconf.async_register_service(self.local_info)

    def _detect_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("224.255.255.255", 1))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()