import logging
import brigadier 

logger = logging.getLogger(__name__)

class ConnectionContext(brigadier.Context):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = kwargs.get("mode")
        self.me = self.mode.me
        self.connection = self.mode.connection

class RestConnectionMode(brigadier.Module):
    def __init__(self, me, connection):
        self.me = me
        self.connection = connection
        self.name = "rest"

        self.parser = brigadier.Parser()
        self.parser.load_module(self)

    async def handle_inbound(self, payload):
        opcode = payload.get("op")
        if opcode is None:
            return {"error" : "No Opcode Provided"}, 400

        arguments = {
            k : v 
            for k, v in payload.items()
            if k != "op"
        }

        context = ConnectionContext(
            parser = self.parser,
            mode = self
        )

        try:
            response = await self.parser.parse(opcode, arguments, context)
        except Exception as e:
            return {"error" : str(e)}, 400
        finally:
            return response, 200

    async def dispatch(self, payload):
        coro = self.me.http_client.post(
                self.connection.ip,
                self.connection.port,
                "/serenity/p2p",
                payload
            )
        await coro

    async def dispatch_ping(self):
        packet = {
            "op" : "PING"
        }
        return await self.dispatch(packet)

    @brigadier.command(name = "PING")
    async def handle_ping(self, ctx):
        return {"response" : "Pong!"}, 200

    async def dispatch_command(self, cmd, arguments):
        ...

    @brigadier.command(name = "COMMAND")
    async def hande_command(self, ctx, cmd, arguments):
        ...

    @brigadier.command(name = "CHANGE_CONNECTION_MODE")
    async def handle_change_connection_mode(self, ctx, mode, arguments = None):
        ...

    @brigadier.command(name = "RECONNECT")
    async def handle_reconnect(self, ctx):
        ...

class Connection:
    """Represents an active connection state with a remote node."""

    def __init__(self, node_uid: str, ip: str, port: int, token_mtt, token_ttm):
        self.node_uid = node_uid
        self.ip = ip
        self.port = port
        self.token_mtt = token_mtt
        self.token_ttm = token_ttm

        # Connection state
        self.is_authenticated = False
        self.mode = None

    def set_mode(self, factory, me):
        self.mode = factory(me, self)

    async def handle_inbound(self, payload: dict) -> dict:
        return await self.mode.handle_inbound(payload)