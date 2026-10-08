import asyncio
import traceback
import inspect
import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)

def listener(event_name: str):
    """
    Decorator for class methods (like discord.py Cog listeners).
    Marks a method as an event handler without needing access to the node instance yet.
    """
    def decorator(func: Callable):
        setattr(func, "__event_listener__", event_name)
        return func
    return decorator


class EventBus:
    def __init__(self):
        # Maps event names to a list of async callbacks
        self._listeners: Dict[str, List[Callable]] = {}

    def on(self, event_name: str):
        """Decorator for direct registration: @node.events.on('peer_discovered')"""
        def decorator(func: Callable):
            self.subscribe(event_name, func)
            return func
        return decorator

    def subscribe(self, event_name: str, callback: Callable):
        """Subscribes an async callback to an event."""
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError(f"Listener for '{event_name}' must be an async function.")
        
        if event_name not in self._listeners:
            self._listeners[event_name] = []
            
        if callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable):
        """Unsubscribes a callback from an event."""
        if event_name in self._listeners and callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)

    def register_listeners_from(self, instance: object):
        """
        Scans an object (like a platform module or manager) for methods decorated 
        with @listener('...') and registers them automatically.
        """
        for _, method in inspect.getmembers(instance, predicate=inspect.ismethod):
            if hasattr(method, "__event_listener__"):
                event_name = getattr(method, "__event_listener__")
                self.subscribe(event_name, method)

    async def dispatch(self, event_name: str, *args, **kwargs):
        """
        Triggers an event. Executes all registered listeners concurrently 
        without blocking the event loop or stopping other listeners on failure.
        """
        if event_name not in self._listeners:
            return

        listeners = self._listeners[event_name]
        if not listeners:
            return

        # Execute all callbacks concurrently on the event loop
        tasks = [asyncio.create_task(listener(*args, **kwargs)) for listener in listeners]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for callback, result in zip(listeners, results):
            if isinstance(result, Exception):
                # Log error or dispatch an internal error event
                logger.info(f"Error in listener '{callback.__name__}' for event '{event_name}': {result}")
                traceback.print_exception(result)