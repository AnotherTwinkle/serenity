class CommandError(Exception):
    pass

class FlagError(CommandError):
    pass

class CommandNotFound(CommandError):
    pass

class CommandAlreadyRegistered(CommandError):
    pass

class CommandNotProvided(CommandError):
    pass

class CheckFailure(CommandError):
    pass

class ModuleError(Exception):
    pass

class ModuleAlreadyRegistered(ModuleError):
    pass

class ModuleAlreadyLoaded(ModuleError):
    pass


