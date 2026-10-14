"""Unit tests for Smart 80% controller state machine and background service."""

import os
import unittest

from lenovo_conservation.battery_monitor import PowerSupplySnapshot
from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareDetector,
)
from lenovo_conservation.lenovo_control import LenovoHardwareController
from lenovo_conservation.service import (
    ControllerState,
    LenovoConservationService,
    ServicePersistentState,
    Smart80Controller,
)
from tests.mock_sysfs import MockSysfs


class TestSmart80Service(unittest.TestCase):
    """Test suite for Smart 80% hysteresis state machine and persistence."""

    def setUp(self):
        self.mock = MockSysfs()
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2", product_version="Lenovo ideapad 330-15ARR")
        self.cm_path = self.mock.setup_ideapad_conservation(initial_value=0)
        self.bat_path = self.mock.setup_battery("BAT0", capacity=70, status="Charging")
        self.ac_path = self.mock.setup_ac_adapter("ADP0", online=1)

        self.detector = HardwareDetector(sys_root=self.mock.sys_dir, proc_root=self.mock.proc_dir)
        self.caps = self.detector.detect()
        self.ctrl = LenovoHardwareController()
        self.smart80 = Smart80Controller(
            hardware_caps=self.caps,
            controller=self.ctrl,
            upper_threshold=80,
            lower_threshold=75,
        )

    def tearDown(self):
        self.mock.cleanup()

    def _make_snapshot(self, capacity: int, ac_online: bool = True, status: str = "Charging") -> PowerSupplySnapshot:
        """Helper to create snapshot with specific capacity and AC state."""
        self.mock.setup_battery("BAT0", capacity=capacity, status=status)
        self.mock.setup_ac_adapter("ADP0", online=1 if ac_online else 0)
        bats, acs = self.detector.scan_power_supplies()
        return PowerSupplySnapshot(
            timestamp=100.0,
            ac_online=ac_online,
            batteries=bats,
            ac_adapters=acs,
        )

    def test_smart80_activation_at_80_percent(self):
        """When battery reaches 80% on AC, conservation mode must be enabled."""
        # Initial hardware mode: disabled (0)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 0)

        snap = self._make_snapshot(capacity=80, ac_online=True)
        state, action = self.smart80.evaluate(snap)

        self.assertEqual(state, ControllerState.CONSERVING_AT_80)
        # Hardware conservation mode must now be 1
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

    def test_smart80_activation_at_overshoot(self):
        """When battery plugs in at >80% (e.g. 85%), conservation mode is enabled."""
        snap = self._make_snapshot(capacity=85, ac_online=True)
        state, action = self.smart80.evaluate(snap)

        self.assertEqual(state, ControllerState.CONSERVING_AT_80)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

    def test_smart80_deactivation_at_75_percent(self):
        """When battery drops to 75% on AC, conservation mode must be disabled to recharge."""
        # Pre-set hardware mode to 1 (conserving)
        self.ctrl.set_conservation_mode(self.cm_path, True)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

        snap = self._make_snapshot(capacity=75, ac_online=True)
        state, action = self.smart80.evaluate(snap)

        self.assertEqual(state, ControllerState.CHARGING_TOWARD_80)
        # Hardware conservation mode must now be 0 (allows charging)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 0)

    def test_hysteresis_zone_no_rapid_toggle(self):
        """Between 76% and 79%, the controller must maintain its current state without toggling."""
        # Scenario 1: Reached 80% -> conserving
        snap80 = self._make_snapshot(capacity=80, ac_online=True)
        self.smart80.evaluate(snap80)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

        # Battery dips slightly to 79% (under heavy load)
        snap79 = self._make_snapshot(capacity=79, ac_online=True)
        state, _ = self.smart80.evaluate(snap79)
        self.assertEqual(state, ControllerState.IN_HYSTERESIS)
        # Mode must REMAIN 1 (does not toggle to 0!)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

        # Battery dips to 77%
        snap77 = self._make_snapshot(capacity=77, ac_online=True)
        state, _ = self.smart80.evaluate(snap77)
        self.assertEqual(state, ControllerState.IN_HYSTERESIS)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 1)

        # Battery drains to 75% -> Now it must switch to charging (mode 0)
        snap75 = self._make_snapshot(capacity=75, ac_online=True)
        state, _ = self.smart80.evaluate(snap75)
        self.assertEqual(state, ControllerState.CHARGING_TOWARD_80)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 0)

        # Battery charges back up to 76%
        snap76 = self._make_snapshot(capacity=76, ac_online=True)
        state, _ = self.smart80.evaluate(snap76)
        self.assertEqual(state, ControllerState.IN_HYSTERESIS)
        # Mode must REMAIN 0 (continues charging toward 80%)
        self.assertEqual(self.ctrl.get_conservation_mode(self.cm_path), 0)

    def test_ac_disconnected_idle_state(self):
        """When AC is disconnected, controller enters IDLE state and does not toggle."""
        snap_unplugged = self._make_snapshot(capacity=80, ac_online=False, status="Discharging")
        state, action = self.smart80.evaluate(snap_unplugged)

        self.assertEqual(state, ControllerState.IDLE_DISCONNECTED)
        self.assertIn("Running on battery", action)

    def test_consecutive_errors_limit(self):
        """Controller halts after max consecutive errors to avoid repeated failing writes."""
        # Point to a read-only sysfs file
        ro_cm_path = self.mock.setup_ideapad_conservation(initial_value=0, writable=False)
        self.caps.interface_path = ro_cm_path
        self.smart80.update_capabilities(self.caps)

        snap = self._make_snapshot(capacity=82, ac_online=True)

        for _ in range(3):
            self.smart80.evaluate(snap)

        self.assertEqual(self.smart80.state, ControllerState.ERROR)
        self.assertGreaterEqual(self.smart80.consecutive_errors, 3)

        # Subsequent evaluation remains in error state and does not spam writes
        state, action = self.smart80.evaluate(snap)
        self.assertEqual(state, ControllerState.ERROR)
        self.assertIn("consecutive write errors", action)

    def test_persistence_and_reboot_recovery(self):
        """Active profile persists to disk and recovers upon service restart."""
        state_file = os.path.join(self.mock.root, "test_state.json")
        pid_file = os.path.join(self.mock.root, "test_service.pid")

        svc1 = LenovoConservationService(state_file=state_file, pid_file=pid_file)
        svc1.detector = self.detector
        svc1.caps = self.caps
        svc1.smart80.update_capabilities(self.caps)

        # Set profile to smart_80
        res = svc1.set_active_profile(ChargingProfile.SMART_80)
        self.assertTrue(res.success)
        self.assertEqual(svc1.persistent_state.active_profile, ChargingProfile.SMART_80.value)

        # Simulate service restart (new service instance loading state from disk)
        svc2 = LenovoConservationService(state_file=state_file, pid_file=pid_file)
        svc2.detector = self.detector
        self.assertEqual(svc2.persistent_state.active_profile, ChargingProfile.SMART_80.value)


if __name__ == "__main__":
    unittest.main()
