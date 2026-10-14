"""Smart 80% background controller and daemon service for Lenovo Conservation.

Enforces the software-managed 80% charging target on hardware with fixed 60%
conservation mode. Monitors battery capacity with hysteresis (80% enable / 75% disable),
handles AC changes, sleep/resume, and persists active profile across reboots.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from lenovo_conservation.battery_monitor import BatteryMonitor, PowerSupplySnapshot
from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareCapabilities,
    HardwareDetector,
    InterfaceType,
)
from lenovo_conservation.lenovo_control import ControlResult, LenovoHardwareController
from lenovo_conservation.privileged_helper import PrivilegedHelper

logger = logging.getLogger("lenovo_conservation.service")


class ControllerState(str, Enum):
    IDLE_DISCONNECTED = "idle_no_ac"
    CHARGING_TOWARD_80 = "charging_toward_80"
    CONSERVING_AT_80 = "conserving_at_80"
    IN_HYSTERESIS = "in_hysteresis"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class ServicePersistentState:
    """State persisted to disk across application restarts and reboots."""
    active_profile: str = ChargingProfile.FULL_CHARGE.value
    smart80_upper: int = 80
    smart80_lower: int = 75
    last_controller_state: str = ControllerState.DISABLED.value
    last_action: str = "Initialized"
    last_updated: float = 0.0
    consecutive_errors: int = 0


def get_state_file_path() -> str:
    """Determine the best path for saving state based on permissions."""
    # If running as root (system service)
    if os.geteuid() == 0:
        system_dir = "/var/lib/lenovo-conservation"
        os.makedirs(system_dir, exist_ok=True)
        return os.path.join(system_dir, "state.json")

    # User level state
    user_config_dir = os.path.expanduser("~/.config/lenovo-conservation")
    os.makedirs(user_config_dir, exist_ok=True)
    return os.path.join(user_config_dir, "state.json")


def get_pid_file_path() -> str:
    """Get the lock/PID file path."""
    if os.geteuid() == 0:
        os.makedirs("/run/lenovo-conservation", exist_ok=True)
        return "/run/lenovo-conservation/service.pid"
    user_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/tmp/lenovo-conservation-{os.getuid()}")
    os.makedirs(user_runtime, exist_ok=True)
    return os.path.join(user_runtime, "service.pid")


class Smart80Controller:
    """State machine controller for the Smart 80% charging target."""

    def __init__(
        self,
        hardware_caps: HardwareCapabilities,
        controller: LenovoHardwareController,
        upper_threshold: int = 80,
        lower_threshold: int = 75,
        max_consecutive_errors: int = 3,
    ):
        self.caps = hardware_caps
        self.ctrl = controller
        self.upper_threshold = upper_threshold
        self.lower_threshold = lower_threshold
        self.max_consecutive_errors = max_consecutive_errors

        self.state = ControllerState.DISABLED
        self.consecutive_errors = 0
        self.last_action = "Controller initialized"
        self._target_path = self.caps.interface_path

    def update_capabilities(self, caps: HardwareCapabilities) -> None:
        """Update hardware interface references."""
        self.caps = caps
        self._target_path = caps.interface_path

    def evaluate(self, snapshot: PowerSupplySnapshot) -> tuple[ControllerState, str]:
        """Evaluate battery percentage and AC power to apply Smart 80% logic."""
        if not self._target_path or not os.path.isfile(self._target_path):
            self.state = ControllerState.ERROR
            self.last_action = f"Hardware interface not accessible: {self._target_path}"
            return self.state, self.last_action

        # Check if error limit reached to prevent repeated failing write attempts
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.state = ControllerState.ERROR
            self.last_action = (
                f"Controller paused: {self.consecutive_errors} consecutive write errors. "
                f"Check permissions or firmware status."
            )
            return self.state, self.last_action

        primary_bat = snapshot.primary_battery
        if not primary_bat or not primary_bat.present:
            self.state = ControllerState.IDLE_DISCONNECTED
            self.last_action = "No battery present"
            return self.state, self.last_action

        # Handle AC disconnected (running on battery)
        if not snapshot.ac_online:
            self.state = ControllerState.IDLE_DISCONNECTED
            self.last_action = f"Running on battery ({primary_bat.capacity}%). Charging suspended."
            return self.state, self.last_action

        current_capacity = primary_bat.capacity
        cur_hardware_mode = self.ctrl.get_conservation_mode(self._target_path)

        # Condition 1: Battery reaches or exceeds upper threshold (e.g. >= 80%)
        # Turn ON native 60% conservation mode to stop charging.
        if current_capacity >= self.upper_threshold:
            if cur_hardware_mode != 1:
                logger.info(
                    "Smart 80: Battery reached %d%% >= %d%%. Enabling conservation mode.",
                    current_capacity,
                    self.upper_threshold,
                )
                res = self.ctrl.set_conservation_mode(self._target_path, True)
                if res.success:
                    self.consecutive_errors = 0
                    self.state = ControllerState.CONSERVING_AT_80
                    self.last_action = (
                        f"Target reached ({current_capacity}%). "
                        f"Native conservation mode enabled to hold charge."
                    )
                else:
                    self.consecutive_errors += 1
                    self.state = ControllerState.ERROR
                    self.last_action = f"Failed to enable conservation mode: {res.message}"
            else:
                self.consecutive_errors = 0
                self.state = ControllerState.CONSERVING_AT_80
                self.last_action = (
                    f"Holding charge at {current_capacity}% "
                    f"(target: {self.upper_threshold}%, conservation active)."
                )

        # Condition 2: Battery falls to or below lower threshold (e.g. <= 75%)
        # Turn OFF conservation mode to resume charging towards 80%.
        elif current_capacity <= self.lower_threshold:
            if cur_hardware_mode != 0:
                logger.info(
                    "Smart 80: Battery drained to %d%% <= %d%%. Disabling conservation mode to recharge.",
                    current_capacity,
                    self.lower_threshold,
                )
                res = self.ctrl.set_conservation_mode(self._target_path, False)
                if res.success:
                    self.consecutive_errors = 0
                    self.state = ControllerState.CHARGING_TOWARD_80
                    self.last_action = (
                        f"Battery drained to {current_capacity}%. "
                        f"Recharging toward {self.upper_threshold}%."
                    )
                else:
                    self.consecutive_errors += 1
                    self.state = ControllerState.ERROR
                    self.last_action = f"Failed to disable conservation mode: {res.message}"
            else:
                self.consecutive_errors = 0
                self.state = ControllerState.CHARGING_TOWARD_80
                self.last_action = (
                    f"Charging toward {self.upper_threshold}% (currently {current_capacity}%)."
                )

        # Condition 3: In hysteresis band (76% - 79%)
        # Maintain current charging state to avoid rapid toggling
        else:
            self.consecutive_errors = 0
            self.state = ControllerState.IN_HYSTERESIS
            if cur_hardware_mode == 1:
                self.last_action = (
                    f"In hysteresis zone ({current_capacity}%). "
                    f"Conservation active (holding until <= {self.lower_threshold}%)."
                )
            else:
                self.last_action = (
                    f"In hysteresis zone ({current_capacity}%). "
                    f"Charging actively (until >= {self.upper_threshold}%)."
                )

        return self.state, self.last_action


class LenovoConservationService:
    """Persistent background service managing battery monitoring and active profiles."""

    def __init__(
        self,
        state_file: Optional[str] = None,
        pid_file: Optional[str] = None,
        detector: Optional[HardwareDetector] = None,
        controller: Optional[LenovoHardwareController] = None,
        helper: Optional[PrivilegedHelper] = None,
    ):
        self.state_file = state_file or get_state_file_path()
        self.pid_file = pid_file or get_pid_file_path()

        self.detector = detector or HardwareDetector()
        self.caps = self.detector.detect()
        self.helper = helper or PrivilegedHelper()
        self.controller = controller or LenovoHardwareController(privileged_helper=self.helper)
        self.monitor = BatteryMonitor(detector=self.detector)

        self.persistent_state = self._load_state()

        self.smart80 = Smart80Controller(
            hardware_caps=self.caps,
            controller=self.controller,
            upper_threshold=self.persistent_state.smart80_upper,
            lower_threshold=self.persistent_state.smart80_lower,
        )

        self._pid_fd: Optional[int] = None
        self._running = False

    def _load_state(self) -> ServicePersistentState:
        """Load persistent state from disk."""
        if os.path.isfile(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return ServicePersistentState(**data)
            except Exception as e:
                logger.warning("Failed to load state file (%s), using defaults", e)
        return ServicePersistentState()

    def save_state(self) -> None:
        """Atomically persist state to disk."""
        tmp_file = f"{self.state_file}.tmp.{os.getpid()}"
        try:
            self.persistent_state.last_updated = time.time()
            data = asdict(self.persistent_state)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            logger.error("Failed to persist service state to %s: %s", self.state_file, e)
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def acquire_pid_lock(self) -> bool:
        """Acquire an exclusive lock on the PID file to prevent duplicate daemons."""
        try:
            self._pid_fd = os.open(self.pid_file, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self._pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(self._pid_fd, 0)
            os.write(self._pid_fd, f"{os.getpid()}\n".encode("utf-8"))
            return True
        except (IOError, OSError):
            logger.error("Another Lenovo Conservation service daemon is already running (PID lock active).")
            if self._pid_fd is not None:
                os.close(self._pid_fd)
                self._pid_fd = None
            return False

    def release_pid_lock(self) -> None:
        """Release PID file lock."""
        if self._pid_fd is not None:
            try:
                fcntl.flock(self._pid_fd, fcntl.LOCK_UN)
                os.close(self._pid_fd)
            except OSError:
                pass
            self._pid_fd = None
        if os.path.exists(self.pid_file):
            try:
                os.remove(self.pid_file)
            except OSError:
                pass

    def set_active_profile(self, profile: ChargingProfile) -> ControlResult:
        """Switch active profile, reconfiguring hardware and background controller."""
        logger.info("Switching active profile to: %s", profile.value)
        self.caps = self.detector.detect()
        self.smart80.update_capabilities(self.caps)

        if profile not in self.caps.supported_profiles and profile != ChargingProfile.FULL_CHARGE:
            return ControlResult(
                success=False,
                message=f"Profile '{profile.value}' is not supported on this hardware ({self.caps.state.value}).",
            )

        res = ControlResult(success=True, message=f"Profile set to {profile.value}")

        if profile == ChargingProfile.CONSERVATION_60 or profile == ChargingProfile.CONSERVATION_80:
            # Native hardware conservation mode
            if self.caps.interface_path:
                res = self.controller.set_conservation_mode(self.caps.interface_path, True)

        elif profile == ChargingProfile.CONFIGURABLE_80:
            # Native ThinkPad thresholds: start 75%, end 80%
            primary = self.caps.primary_battery
            if primary and primary.charge_end_threshold_path:
                res = self.controller.set_thresholds(
                    primary.charge_start_threshold_path,
                    primary.charge_end_threshold_path,
                    75,
                    80,
                )

        elif profile == ChargingProfile.FULL_CHARGE:
            # Disable conservation / restore normal charge
            if self.caps.interface_type == InterfaceType.IDEAPAD_CONSERVATION:
                if self.caps.interface_path:
                    res = self.controller.set_conservation_mode(self.caps.interface_path, False)
            elif self.caps.interface_type == InterfaceType.THINKPAD_THRESHOLDS:
                primary = self.caps.primary_battery
                if primary and primary.charge_end_threshold_path:
                    res = self.controller.set_thresholds(
                        primary.charge_start_threshold_path,
                        primary.charge_end_threshold_path,
                        96,
                        100,
                    )

        elif profile == ChargingProfile.SMART_80:
            # Immediate evaluation for Smart 80%
            snap = self.monitor.get_snapshot()
            state, action = self.smart80.evaluate(snap)
            res = ControlResult(
                success=True,
                message=f"Smart 80% controller active. {action}",
            )

        if res.success:
            self.persistent_state.active_profile = profile.value
            self.save_state()

        return res

    def _on_power_supply_change(self, snapshot: PowerSupplySnapshot) -> None:
        """Handle power supply update from BatteryMonitor."""
        active_prof = self.persistent_state.active_profile

        if active_prof == ChargingProfile.SMART_80.value:
            state, action = self.smart80.evaluate(snapshot)
            self.persistent_state.last_controller_state = state.value
            self.persistent_state.last_action = action
            self.save_state()

    def run_daemon(self) -> None:
        """Run the service loop indefinitely."""
        if not self.acquire_pid_lock():
            sys.exit(1)

        self._running = True

        def sig_handler(signum, frame):
            logger.info("Service received signal %s, stopping...", signum)
            self._running = False
            self.monitor.stop()

        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)

        logger.info("Starting Lenovo Conservation Service (profile: %s)...", self.persistent_state.active_profile)

        # Register callback and start monitor
        self.monitor.add_callback(self._on_power_supply_change)
        self.monitor.start()

        # Enforce current profile on startup (recovery after reboot)
        try:
            current_profile = ChargingProfile(self.persistent_state.active_profile)
            self.set_active_profile(current_profile)
        except Exception as e:
            logger.error("Failed to restore active profile on startup: %s", e)

        try:
            while self._running:
                time.sleep(1.0)
        finally:
            self.monitor.stop()
            self.release_pid_lock()
            logger.info("Lenovo Conservation Service stopped cleanly.")


def main_service() -> int:
    """CLI entry point for the daemon service."""
    import argparse

    parser = argparse.ArgumentParser(description="Lenovo Conservation Background Service")
    parser.add_argument("--profile", choices=[p.value for p in ChargingProfile], help="Set active charging profile")
    parser.add_argument("--status", action="store_true", help="Print current status and exit")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    svc = LenovoConservationService()

    if args.status:
        state = svc.persistent_state
        caps = svc.caps
        snap = svc.monitor.get_snapshot()
        print(f"Device: {caps.laptop_vendor} {caps.product_version or caps.product_name}")
        print(f"Capability: {caps.state.value}")
        print(f"Active Profile: {state.active_profile}")
        print(f"Battery: {snap.capacity}% ({snap.status}), AC Online: {snap.ac_online}")
        print(f"Controller State: {state.last_controller_state}")
        print(f"Last Action: {state.last_action}")
        return 0

    if args.profile:
        target = ChargingProfile(args.profile)
        res = svc.set_active_profile(target)
        print(res.message)
        return 0 if res.success else 1

    # Default: run daemon
    svc.run_daemon()
    return 0


if __name__ == "__main__":
    sys.exit(main_service())
