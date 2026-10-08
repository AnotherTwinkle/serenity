import asyncio
from typing import Any, Optional
from aiohttp import web, ClientTimeout
import aiohttp
import logging
import tokens
from connection import Connection, RestConnectionMode
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HttpGateway:
	def __init__(self, node: Any, host: str = "0.0.0.0", port: int = 2406):
		self.node = node
		self.host = host
		self.port = port

		self.app: Optional[web.Application] = None
		self.runner: Optional[web.AppRunner] = None
		self.site: Optional[web.TCPSite] = None

	async def start(self) -> None:
		self.app = web.Application()
		self._setup_routes()

		# Non-blocking web runner setup
		self.runner = web.AppRunner(self.app)
		await self.runner.setup()

		self.site = web.TCPSite(self.runner, self.host, self.port)
		await self.site.start()
		logger.info(f"Server operational on http://{self.host}:{self.port}")

	async def stop(self) -> None:
		if self.runner:
			await self.runner.cleanup()

	def _setup_routes(self) -> None:
		self.app.add_routes([
			web.post('/serenity/hello', self.handle_hello),
			web.post('/serenity/authenticate', self.handle_authenticate),
			web.post('/serenity/p2p', self.handle_p2p_command),
		])

	async def handle_hello(self, request: web.Request):
			try:
				payload = await request.json()
			except Exception:
				return web.json_response({"error": "Invalid JSON body"}, status=400)

			uid = payload.get("uid")
			if not uid:
				return web.json_response({"error": "Missing uid in payload"}, status=400)

			resuming = False
			if uid in self.node.connections:
				response_data = {
					"op": "RESUME",
					"token_ytm": self.node.connections[uid].token_ttm,
					"token_mty": self.node.connections[uid].token_mtt,
					"connection_mode" : self.node.connections[uid].mode.name
				}
				resuming = True
			else:
				response_data = {
					"op": "HELLO"
				}

			# Handling authentication logic
			if not resuming and self.node.config.get('uid') > uid:
				async def trigger_auth():
					# Active resolution fixes the race condition entirely
					host = await self.node.zeroconf.resolve_host_by_uid(uid)
					if host:
						logger.info(f"Host {uid} resolved. Authenticating...")
						await self.node.authenticate_with_host(host)
					else:
						logger.error(f"Could not resolve host info for uid {uid} to authenticate.")
				
				# Schedule safely without blocking the web response
				loop = asyncio.get_running_loop()
				loop.call_soon(asyncio.create_task, trigger_auth())

			return web.json_response(response_data, status=200)
		
	async def handle_get_node(self, request: web.Request) -> web.Response:
		node_identity = {
			"uid" : self.node.config.get("uid", "serenity-node-default"),
			"version": self.node.config.get("version", "1.0.0"),
			"platform": self.node.config.get("platform", "linux"),
			"connection_modes": ["rest-p2p", "wss"],
		}
		return web.json_response(node_identity)

	async def handle_authenticate(self, request: web.Request) -> web.Response:
		"""
		POST /serenity/authenticate
		Receives an incoming peer's node identity and authentication password.
		"""
		try:
			payload = await request.json()
		except Exception:
			return web.json_response({"error": "Invalid JSON body"}, status=400)

		peer_uid = payload.get("uid")
		password = payload.get("password")  # Target device password provided by peer
		ip = payload.get("ip")
		port = payload.get("port")
		required_token = payload.get("required_token")

		if not peer_uid:
			return web.json_response({"error": "Missing peer UID"}, status=400)

		expected_password = self.node.config.get("password", None)
		if expected_password and password != expected_password:
			return web.json_response({"accepted": False, "reason": "Unauthorized"}, status=401)

		generated_token = tokens.generate_token(peer_uid, self.node.config.get("secret"))
		self.node.connections[peer_uid] = Connection(node_uid = peer_uid, ip = ip, port = port, token_mtt = required_token, token_ttm = generated_token)
		self.node.connections[peer_uid].set_mode(RestConnectionMode, self.node)

		logger.info(f"Successfully authenticated node: {peer_uid}")

		# Dispatch event on the node's EventBus
		await self.node.events.dispatch("node_authenticated", peer_uid=peer_uid, payload=payload)
		
		# Return connection parameters & available commands
		response_data = {
			"token" : generated_token,
			"accepted": True,
			"available_modes": ["rest", "wss"],
			"commands": [],
		}
		return web.json_response(response_data, status = 200)

	async def handle_p2p_command(self, request: web.Request) -> web.Response:
		"""
		POST /serenity/p2p
		Endpoint for executing incoming commands over the rest-p2p connection mode.
		"""
		try:
			payload = await request.json()
		except Exception:
			return web.json_response({"error": "Invalid JSON body"}, status=400)

		# First determine node uid from request token 
		token = request.headers.get('Authorization')
		if token is None:
			return web.json_response({"error" : "Missing auth header"}, status = 400)

		uid, timedata = tokens.decode_token(token, self.node.config['secret'])

		conn = self.node.connections.get(uid, None)
		if conn is None:
			return web.json_response({"error" : "You are not authenticated."}, status = 400)

		if conn.mode.name != "rest":
			return web.json_response({"error"  "This mode is not enabled for this connection"}, status = 400)

		result, status = await conn.handle_inbound(payload)
		return web.json_response(result, status = status)

class NodeUnreachableError(Exception):
	"""Raised when a remote peer cannot be reached over HTTP."""
	pass


class HttpClient:
	def __init__(self, node):
		self.node = node
		self._session: aiohttp.ClientSession | None = None

	async def start(self) -> None:
		"""Initializes the shared aiohttp ClientSession with TCP socket pooling."""
		headers = {
			"User-Agent": f"SerenityNode/{(self.node.config.get('version', '1.0'))}",
			"X-Serenity-Sender": self.node.config.get("uid"),
			"Content-Type": "application/json",
		}

		timeout = aiohttp.ClientTimeout(total=15, connect=5)
		self._session = aiohttp.ClientSession(
			headers=headers,
			timeout=timeout
		)

	async def stop(self) -> None:
		"""Closes the underlying aiohttp session during node shutdown."""
		if self._session and not self._session.closed:
			await self._session.close()

	async def post(self, ip: str, port: int, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
		"""Sends an outbound JSON POST request to a peer."""
		if not self._session:
			raise RuntimeError("HttpClient is not started.")

		if asyncio.current_task() is None:
			return await asyncio.create_task(self.post(ip, port, path, payload))

		url = f"http://{ip}:{port}{path}"
		headers = {}

		matches = [conn.token_mtt for conn in self.node.connections.values() if conn.ip == ip and conn.port == port]
		if matches:
			headers = {"Authorization" : matches[0]}

		try:
			async with self._session.post(url, json=payload, headers = headers, timeout=ClientTimeout(total=None)) as response:
				response.raise_for_status()
				data = await response.json()
				return response, data

		except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
			raise NodeUnreachableError(f"Failed to connect to node at {url}: {e}") from e
		except aiohttp.ClientResponseError as e:
			raise NodeUnreachableError(f"Node at {url} returned HTTP status {e.status}") from e

	async def get(self, ip: str, port: int, path: str) -> Dict[str, Any]:
		"""Sends an outbound JSON GET request to fetch remote node metadata."""
		if not self._session:
			raise RuntimeError("HttpClient is not started.")

		if asyncio.current_task() is None:
			return await asyncio.create_task(self.post(ip, port, path, payload))

		url = f"http://{ip}:{port}{path}"
		headers = {}

		matches = [conn.token_mtt for conn in self.node.connections if conn.ip == ip and conn.port == port]
		if matches:
			headers = {"Authorization" : matches[0]}

		try:
			async with self._session.get(url, headers = headers, timeout=ClientTimeout(total=None)) as response:
				response.raise_for_status()
				data = await response.json()
				return response, data

		except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
			raise NodeUnreachableError(f"Failed to connect to node at {url}: {e}") from e

		except aiohttp.ClientResponseError as e:
			raise NodeUnreachableError(f"Node at {url} returned HTTP status {e.status}") from e
