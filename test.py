import brigadier as commands
import asyncio
import random 

parser = commands.Parser()

class SerenityContext(commands.Context):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conn_mode = kwargs.get("conn_mode")

def require_connection_mode(conn_mode):
	def predicate(ctx):
		print(ctx.conn_mode, conn_mode)
		return ctx.conn_mode == conn_mode

	return commands.check(predicate)

class M(commands.Module):
	def __init__(self, a = '0'):
		self.parser = commands.Parser()
		self.parser.load_module(self)

	@require_connection_mode("wss")
	@commands.command(name = "foo")
	async def foo(self, ctx, a, b):
		await asyncio.sleep(random.randint(1, 5))
		raise e
		print(f"Hello {a}, {b} is calling!")

		@foo.error
		async def foo_error(ctx, error):
			print(error)

async def main():
	m = M()
	coros = [
		m.parser.parse(name = "foo",
					 arguments = {"a" : i, "b" : i + 1},
					 ctx = SerenityContext(parser = m.parser, conn_mode = random.choice(["wss", "rest-p2p"]))
					 )
		for i in range(3)
	]
	await asyncio.gather(*coros)

async def _main():
	coros = [
		parser.parse(name = "foo",
					 arguments = {"a" : i, "b" : i + 1},
					 ctx = SerenityContext(parser = parser, conn_mode = random.choice(["wss", "rest-p2p"]))
					 )
		for i in range(3)
	]

	await asyncio.gather(*coros)

asyncio.run(main())