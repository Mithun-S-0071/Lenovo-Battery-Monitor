"""Battery and AC power monitor module for Lenovo Conservation.

Combines Linux kernel uevent netlink notifications with an intelligent,
adaptive polling timer fallback. Dispatches updates to registered callbacks.
"""

from __future__ import annotations

import logging
import os
import socket
import select
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from lenovo_conservation.hardware_detection import (
    ACAdapterInfo,
    BatteryInfo,
    HardwareDetector,
)

logger = logging.getLogger("lenovo_conservation.monitor")


@dataclass
class PowerSupplySnapshot:
    """Current snapshot of power supplies and battery status."""
    timestamp: float
    ac_online: bool
    batteries: List[BatteryInfo]
    ac_adapters: List[ACAdapterInfo]

    @property
    def primary_battery(self) -> Optional[BatteryInfo]:
        for b in self.batteries:
            if b.present:
                return b
        return self.batteries[0] if self.batteries else None

    @property
    def capacity(self) -> int:
        primary = self.primary_battery
        return primary.capacity if primary else 0

    @property
    def status(self) -> str:
        primary = self.primary_battery
        return primary.status if primary else "Unknown"


class BatteryMonitor:
    """Monitors battery and AC state with uevent listener and adaptive polling."""

    def __init__(
        self,
        detector: Optional[HardwareDetector] = None,
        poll_interval_ac: float = 10.0,
        poll_interval_bat: float = 30.0,
    ):
        self.detector = detector or HardwareDetector()
        self.poll_interval_ac = poll_interval_ac
        self.poll_interval_bat = poll_interval_bat

        self._callbacks: List[Callable[[PowerSupplySnapshot], None]] = []
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._uevent_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_snapshot: Optional[PowerSupplySnapshot] = None
        self._lock = threading.Lock()

    def add_callback(self, cb: Callable[[PowerSupplySnapshot], None]) -> None:
        """Register a callback for power supply changes."""
        with self._lock:
            if cb not in self._callbacks:
                self._callbacks.append(cb)

    def remove_callback(self, cb: Callable[[PowerSupplySnapshot], None]) -> None:
        """Unregister a callback."""
        with self._lock:
            if cb in self._callbacks:
                self._callbacks.remove(cb)

    def get_snapshot(self) -> PowerSupplySnapshot:
        """Read current battery and AC state immediately."""
        bats, acs = self.detector.scan_power_supplies()
        ac_online = any(ac.online for ac in acs)
        snapshot = PowerSupplySnapshot(
            timestamp=time.time(),
            ac_online=ac_online,
            batteries=bats,
            ac_adapters=acs,
        )
        with self._lock:
            self._last_snapshot = snapshot
        return snapshot

    def start(self) -> None:
        """Start the background monitor threads."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Start adaptive polling thread
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="LenovoBatteryPollThread",
            daemon=True,
        )
        self._poll_thread.start()

        # Attempt to start uevent listener thread
        self._uevent_thread = threading.Thread(
            target=self._uevent_loop,
            name="LenovoUeventThread",
            daemon=True,
        )
        self._uevent_thread.start()

        logger.info("BatteryMonitor started (poll_ac=%ss, poll_bat=%ss)", self.poll_interval_ac, self.poll_interval_bat)

    def stop(self) -> None:
        """Stop background monitor threads."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)
        if self._uevent_thread and self._uevent_thread.is_alive():
            self._uevent_thread.join(timeout=1.0)

        logger.info("BatteryMonitor stopped.")

    def _notify(self, snapshot: PowerSupplySnapshot) -> None:
        """Dispatch snapshot to all registered callbacks."""
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(snapshot)
            except Exception as e:
                logger.exception("Error in BatteryMonitor callback: %s", e)

    def _poll_loop(self) -> None:
        """Adaptive polling loop."""
        # Initial check
        snapshot = self.get_snapshot()
        self._notify(snapshot)

        while not self._stop_event.is_set():
            # Adaptive sleep duration based on AC state and capacity
            interval = self.poll_interval_ac if snapshot.ac_online else self.poll_interval_bat

            # Wake up if stop requested
            if self._stop_event.wait(timeout=interval):
                break

            new_snapshot = self.get_snapshot()
            # Notify if any meaningful change occurred
            if self._has_changed(snapshot, new_snapshot):
                self._notify(new_snapshot)
            snapshot = new_snapshot

    def _uevent_loop(self) -> None:
        """Listen to kernel netlink uevents for power_supply subsystem changes."""
        netlink_sock = None
        try:
            # NETLINK_KOBJECT_UEVENT is 15
            netlink_sock = socket.socket(
                socket.AF_NETLINK,
                socket.SOCK_RAW,
                15,
            )
            # Bind to netlink
            netlink_sock.bind((os.getpid(), 1))
            netlink_sock.setblocking(False)
        except Exception as e:
            logger.info("Netlink uevent socket not available (%s); relying on sysfs polling fallback", e)
            if netlink_sock:
                netlink_sock.close()
            return

        try:
            while not self._stop_event.is_set():
                r, _, _ = select.select([netlink_sock], [], [], 1.0)
                if not r:
                    continue

                try:
                    data = netlink_sock.recv(4096)
                    decoded = data.decode("utf-8", errors="replace")
                    if "SUBSYSTEM=power_supply" in decoded:
                        # Debounce slightly and read new snapshot
                        time.sleep(0.1)
                        snap = self.get_snapshot()
                        self._notify(snap)
                except (OSError, socket.error):
                    break
        finally:
            if netlink_sock:
                netlink_sock.close()

    def _has_changed(self, old: Optional[PowerSupplySnapshot], new: PowerSupplySnapshot) -> bool:
        """Check if AC status, battery percentage, or charge status changed."""
        if old is None:
            return True
        if old.ac_online != new.ac_online:
            return True
        if old.capacity != new.capacity:
            return True
        if old.status != new.status:
            return True
        if len(old.batteries) != len(new.batteries):
            return True
        return False
