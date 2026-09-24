import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFair

class TelemetryDispatcher:
    """A highly concurrent state manager for robotics and real-time dashboards."""
    
    def __init__(self):
        # Fair scheduling reduces starvation risk but does not promise strict alternation.
        self._lock = AsyncRWLockFair()
        self._state: Dict[str, float] = {"alt": 0.0, "lat": 0.0, "lon": 0.0}

    async def ingest_sensor_data(self, new_data: Dict[str, float]) -> None:
        """
        Called by a high-frequency sensor reader (e.g., UDP stream).
        """
        async with self._lock.write:
            self._state.update(new_data)
        # Simulate processing outside the critical section.
        await asyncio.sleep(0.001)

    async def broadcast_to_clients(self) -> None:
        """
        Called by multiple WebSocket connections concurrently.
        """
        async with self._lock.read:
            # Safely copy the state quickly to minimize lock holding time
            current_state = self._state.copy()
            
        # Dispatch to network OUTSIDE the lock to ensure max throughput
        await self._network_send(current_state)

    async def _network_send(self, data: Dict[str, float]) -> None:
        """Simulates network latency over WebSocket."""
        await asyncio.sleep(0.01)

async def main():
    dispatcher = TelemetryDispatcher()

    async def sensor_loop():
        for i in range(1, 4):
            print(f"[SENSOR] Ingesting altitude {i * 10.0}m...")
            await dispatcher.ingest_sensor_data({"alt": i * 10.0})
            await asyncio.sleep(0.02) # High frequency

    async def websocket_client_loop():
        for _ in range(3):
            await dispatcher.broadcast_to_clients()
            await asyncio.sleep(0.03)

    # Run sensor ingest and multiple websocket clients concurrently
    await asyncio.gather(
        sensor_loop(),
        websocket_client_loop(),
        websocket_client_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
