"""Profile manager module for Lenovo Conservation.

Coordinates hardware detection, profile switching, background service communication,
and user preferences for desktop and CLI interfaces.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

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
from lenovo_conservation.service import (
    ControllerState,
    LenovoConservationService,
    ServicePersistentState,
    get_pid_file_path,
    get_state_file_path,
)

logger = logging.getLogger("lenovo_conservation.profile_manager")


@dataclass
class ServiceHealth:
    is_running: bool
    pid: Optional[int]
    systemd_enabled: bool
    state: ServicePersistentState


class ProfileManager:
    """High-level manager for charging profiles and system state."""

    def __init__(
        self,
        detector: Optional[HardwareDetector] = None,
        controller: Optional[LenovoHardwareController] = None,
        helper: Optional[PrivilegedHelper] = None,
    ):
        self.detector = detector or HardwareDetector()
        self.helper = helper or PrivilegedHelper()
        self.controller = controller or LenovoHardwareController(privileged_helper=self.helper)
        self.monitor = BatteryMonitor(detector=self.detector)

        self.caps: HardwareCapabilities = self.detector.detect()
        self.state_file = get_state_file_path()
        self.pid_file = get_pid_file_path()

    def refresh_hardware(self) -> HardwareCapabilities:
        """Re-probe hardware interfaces and return updated capabilities."""
        self.caps = self.detector.detect()
        return self.caps

    def get_supported_profiles(self) -> List[ChargingProfile]:
        """Return the list of profiles supported by the detected hardware."""
        return list(self.caps.supported_profiles)

    def get_persistent_state(self) -> ServicePersistentState:
        """Read current persisted profile and controller state from disk."""
        if os.path.isfile(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return ServicePersistentState(**data)
            except Exception as e:
                logger.warning("Error reading state file: %s", e)
        return ServicePersistentState()

    def get_active_profile(self) -> ChargingProfile:
        """Determine active profile from persistent state or live hardware."""
        state = self.get_persistent_state()
        try:
            return ChargingProfile(state.active_profile)
        except ValueError:
            pass

        # Fallback to inspecting current hardware state
        if self.caps.interface_type == InterfaceType.IDEAPAD_CONSERVATION:
            if self.caps.interface_path:
                val = self.controller.get_conservation_mode(self.caps.interface_path)
                if val == 1:
                    if self.caps.state == CapabilityState.CONSERVATION_80:
                        return ChargingProfile.CONSERVATION_80
                    return ChargingProfile.CONSERVATION_60
        return ChargingProfile.FULL_CHARGE

    def get_service_health(self) -> ServiceHealth:
        """Inspect background service PID and systemd unit status."""
        is_running = False
        pid: Optional[int] = None

        if os.path.isfile(self.pid_file):
            try:
                with open(self.pid_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        candidate_pid = int(content)
                        # Check if process is alive
                        try:
                            os.kill(candidate_pid, 0)
                            is_running = True
                            pid = candidate_pid
                        except OSError:
                            pass
            except Exception:
                pass

        # Check systemd status if systemctl exists
        systemd_enabled = False
        if shutil.which("systemctl"):
            try:
                res = subprocess.run(
                    ["systemctl", "is-enabled", "lenovo-conservation.service"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                systemd_enabled = (res.returncode == 0)
                if not is_running:
                    active_res = subprocess.run(
                        ["systemctl", "is-active", "lenovo-conservation.service"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    is_running = (active_res.stdout.strip() == "active")
            except Exception:
                pass

        state = self.get_persistent_state()
        return ServiceHealth(
            is_running=is_running,
            pid=pid,
            systemd_enabled=systemd_enabled,
            state=state,
        )

    def apply_profile(self, profile: ChargingProfile) -> ControlResult:
        """Apply the requested charging profile to hardware and service."""
        # Check if supported
        if profile not in self.caps.supported_profiles and profile != ChargingProfile.FULL_CHARGE:
            return ControlResult(
                success=False,
                message=(
                    f"Profile '{profile.value}' is not supported on this device "
                    f"({self.caps.state.value})."
                ),
            )

        # Use LenovoConservationService to apply and persist
        service = LenovoConservationService(
            state_file=self.state_file,
            pid_file=self.pid_file,
            detector=self.detector,
            controller=self.controller,
            helper=self.helper,
        )
        res = service.set_active_profile(profile)

        # If Smart 80% is chosen and background daemon is not yet running, notify user or launch
        if profile == ChargingProfile.SMART_80 and res.success:
            health = self.get_service_health()
            if not health.is_running:
                # Attempt to launch user background daemon or systemd service
                self.ensure_background_service_running()

        return res

    def ensure_background_service_running(self) -> bool:
        """Start the background service daemon if not already running."""
        health = self.get_service_health()
        if health.is_running:
            return True

        # Check if systemd unit is available and try systemctl
        if shutil.which("systemctl"):
            try:
                # Check user service first, then system
                subprocess.run(
                    ["systemctl", "--user", "start", "lenovo-conservation.service"],
                    capture_output=True,
                    timeout=5,
                )
                if self.get_service_health().is_running:
                    return True
            except Exception:
                pass

        # Fallback to spawning daemon process in background
        daemon_bin = shutil.which("lenovo-conservation-daemon")
        if not daemon_bin:
            daemon_bin = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "bin", "lenovo-conservation-daemon")
            )

        if os.path.isfile(daemon_bin) and os.access(daemon_bin, os.X_OK):
            try:
                subprocess.Popen(
                    [sys.executable, daemon_bin, "--daemon"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except Exception as e:
                logger.error("Failed to spawn background daemon: %s", e)
        return False
