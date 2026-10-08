import asyncio
import signal
import code 
import logging
import json
import traceback

from IPython import embed
from typing import Set, Optional

import tokens
from eventbus import EventBus
from zeroconfservice import ZeroconfService, DiscoveredHost
from connection import Connection, RestConnectionMode
from httpservice import HttpGateway, HttpClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GatewayContainer:
	def __init__(self, node):
		self.http = HttpGateway(node, host = "0.0.0.0", port = 2406)
		self.wss = None

class SerenityNode:
	def __init__(self, config_path: str = "config.json"):
		self.config_path: str = config_path
		with open(config_path, 'r') as f:
			self.config = json.load(f)

		self.events: EventBus = EventBus()     # Central async event pub/sub dispatcher

		self.peers: Optional[Any] = None        # PeerRegistry: Tracks discovered peers, UIDs, and active sessions
		self.zeroconf: Optional[Any] = None    # ZeroconfService: mDNS discovery scanner and presence advertiser
		self.connections : Dict[str, Connection] = {}
		self.gateway: Optional[Any] = None      # NetworkGateway: Manages raw HTTP server & WebSocket server listener

		self._background_tasks: Set[asyncio.Task] = set() # Strong references to long-running background tasks
		self._running: bool = False                       # Node operational state flag

	def spawn_task(self, coroutine) -> asyncio.Task:
		"""
		Wraps a coroutine in an asyncio.Task, tracks it to prevent garbage collection,
		and cleans up when completed.
		"""
		task = asyncio.create_task(coroutine)
		self._background_tasks.add(task)
		task.add_done_callback(self._background_tasks.discard)
		return task

	async def start(self):
		"""Initializes components and launches all background tasks/servers concurrently."""
		if self._running:
			return
		self._running = True
		
		# 1. Instantiate subsystems (Pass self as the central container context)
		# self.config = NodeConfig.load(self.config_path)
		# self.peers = PeerRegistry(self)s

		self.gateway = GatewayContainer(self)
		self.http_client = HttpClient(self)
		self.zeroconf = ZeroconfService(self, port = 2406)

		await self.http_client.start()
		await self.zeroconf.start()
		await self.gateway.http.start()


		# 2. Automatically register listeners from loaded modules
		self.events.register_listeners_from(self.zeroconf)

		# Dispatch node started event
		await self.events.dispatch("node_started", node=self)

	async def stop(self):
		"""Gracefully shuts down all servers, services, and background tasks."""
		if not self._running:
			return
		
		self._running = False
		await self.events.dispatch("node_stopping", node=self)

		await self.zeroconf.stop()
		await self.gateway.http.stop()

		# Cancel all active background tasks
		for task in list(self._background_tasks):
			task.cancel()

		# Wait for all tasks to stop handling cancellations
		if self._background_tasks:
			await asyncio.gather(*self._background_tasks, return_exceptions=True)

		logging.info("Shutdown complete.")

	async def authenticate_with_host(self, host):
		host_uid = host.properties.get("uid")
		me_uid = self.config.get("uid")

		password = "loonix"
		ip = self.zeroconf._detect_local_ip()
		port = self.zeroconf.port

		required_token = tokens.generate_token(host_uid, self.config.get("secret"))

		payload = {
			"ip" : ip,
			"port" : port,
			"uid" : me_uid,
			"password": password,
			"required_token" : required_token
		}

		response, data = await self.http_client.post(host.primary_ip, host.port, "/serenity/authenticate", payload)
		if response.status != 200:
			logger.error(f"Cannot connect to {host_uid}. (Status : {respose.status}). Server returned {data}")
			return

		self.connections[host_uid] = Connection(node_uid = host_uid, ip = host.primary_ip, port = host.port, token_mtt = data['token'], token_ttm = required_token)
		self.connections[host_uid].set_mode(RestConnectionMode, self)

node = SerenityNode()

@node.events.on("node_discovered")
async def on_peer_discovery(host: DiscoveredHost):
	host_uid = host.properties.get("uid")
	me_uid = node.config.get("uid")

	if not host_uid or host_uid in node.connections:
		return

	try:
		response, data = await node.http_client.post(
			host.primary_ip, 
			host.port, 
			"/serenity/hello", 
			{"uid": me_uid, "password": "loonix"}
		)
	except Exception as e:
		logger.error(f"Failed to connect to {host_uid} for hello handhake: {e}")
		return

	if response.status != 200:
		logger.error(f"Cannot send hello to {host_uid}. (Status : {response.status}). Server returned {data}")
		return

	if data and data.get("op") == "RESUME":
		logger.info(f"Resuming connection with {host_uid}...")
		node.connections[host_uid] = Connection(
			node_uid=host_uid, 
			ip=host.primary_ip, 
			port=host.port, 
			token_mtt=data.get('token_ytm'), 
			token_ttm=data.get('token_mty')
		)
		node.connections[host_uid].set_mode({
			"rest" : RestConnectionMode
			}[data.get('connection_mode')],
			node
			)

@node.events.on("node_lost")
async def on_peer_lost(host: DiscoveredHost):
	pass

async def run_p2p_tests(node, client):
	"""Background loop executing tests periodically on the main event loop."""
	print("[Test Runner] Started background test task.")
	await asyncio.sleep(5)
	while True:
		try:
			c = list(node.connections.values())[0]

			if node.config['uid'] == 'serenity-ideapad':
				response = await c.mode.dispatch_ping()
				print(f"[Test Runner] Test successful: {response}")

			if node.config['uid'] == 'serenity-a15':
				pass

		except asyncio.CancelledError:
			# Clean exit when the task is canceled during shutdown
			print("[Test Runner] Stopping test loop...")
			break
		except Exception as e:
			# Catch test failures so the loop doesn't crash
			print(f"[Test Runner] Test failed with error: {e}")
			traceback.print_exception(e)
		await asyncio.sleep(10)
		# Wait before running the next iteration
		
async def start_async_repl(namespace: dict):
	# Retrieve the exact loop that node and client session are using
	loop = asyncio.get_running_loop()

	def _run_ipython():
		# Bind user namespace and explicitly associate the main loop
		embed(
			header="\n=== Serenity Async REPL ===\n",
			user_ns=namespace,
			using="asyncio",
		)

	# Note: If running in thread, sync calls in REPL need thread-safe dispatch
	await asyncio.to_thread(_run_ipython)

async def main():
	# 1. Start the Serenity Node
	await node.start()

	# 2. Setup signal handling
	loop = asyncio.get_running_loop()
	stop_event = asyncio.Event()

	def _signal_handler():
		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):
		try:
			loop.add_signal_handler(sig, _signal_handler)
		except NotImplementedError:
			pass

	# 3. Create concurrent tasks for REPL and signal waiting
	repl_task = asyncio.create_task(
		start_async_repl(globals()), name="AsyncREPL"
	)

	test_task = asyncio.create_task(
        run_p2p_tests(node, node.http_client), name="P2PTestLoop"
    )

	stop_task = asyncio.create_task(stop_event.wait(), name="StopSignalWait")

	try:
		await asyncio.wait(
			[stop_task, repl_task, test_task], return_when=asyncio.FIRST_COMPLETED
		)
	except KeyboardInterrupt:
		pass
	finally:
		for task in (stop_task, repl_task, test_task):
			if not task.done():
				task.cancel()
		await node.stop()


if __name__ == "__main__":
	asyncio.run(main())