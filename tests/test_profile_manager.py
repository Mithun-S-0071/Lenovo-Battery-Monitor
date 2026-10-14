"""Unit tests for ProfileManager module."""

import os
import unittest

from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareDetector,
)
from lenovo_conservation.profile_manager import ProfileManager
from tests.mock_sysfs import MockSysfs


class TestProfileManager(unittest.TestCase):
    """Test suite for ProfileManager operations and profile transitions."""

    def setUp(self):
        self.mock = MockSysfs()
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2", product_version="Lenovo ideapad 330-15ARR")
        self.cm_path = self.mock.setup_ideapad_conservation(initial_value=0)
        self.mock.setup_battery("BAT0", capacity=70, status="Charging")
        self.mock.setup_ac_adapter("ADP0", online=1)

        self.detector = HardwareDetector(sys_root=self.mock.sys_dir, proc_root=self.mock.proc_dir)
        self.mgr = ProfileManager(detector=self.detector)

        # Use mock state and pid paths
        self.mgr.state_file = os.path.join(self.mock.root, "profile_mgr_state.json")
        self.mgr.pid_file = os.path.join(self.mock.root, "profile_mgr_service.pid")

    def tearDown(self):
        self.mgr.monitor.stop()
        self.mock.cleanup()

    def test_get_supported_profiles(self):
        """Verify supported profiles returned match hardware capabilities."""
        profs = self.mgr.get_supported_profiles()
        self.assertIn(ChargingProfile.CONSERVATION_60, profs)
        self.assertIn(ChargingProfile.SMART_80, profs)
        self.assertIn(ChargingProfile.FULL_CHARGE, profs)
        self.assertNotIn(ChargingProfile.CONSERVATION_80, profs)

    def test_apply_valid_profile(self):
        """Apply supported profile conservation_60."""
        res = self.mgr.apply_profile(ChargingProfile.CONSERVATION_60)
        self.assertTrue(res.success)
        self.assertEqual(self.mgr.controller.get_conservation_mode(self.cm_path), 1)

    def test_apply_unsupported_profile_rejection(self):
        """Reject profile not supported on current hardware."""
        # On 60% IdeaPad, conservation_80 is unsupported
        res = self.mgr.apply_profile(ChargingProfile.CONSERVATION_80)
        self.assertFalse(res.success)
        self.assertIn("not supported", res.message)

    def test_apply_full_charge_restores_charging(self):
        """Switching to full charge disables conservation mode."""
        self.mgr.controller.set_conservation_mode(self.cm_path, True)
        self.assertEqual(self.mgr.controller.get_conservation_mode(self.cm_path), 1)

        res = self.mgr.apply_profile(ChargingProfile.FULL_CHARGE)
        self.assertTrue(res.success)
        self.assertEqual(self.mgr.controller.get_conservation_mode(self.cm_path), 0)

    def test_service_health_check(self):
        """Inspect health status when no daemon is active."""
        health = self.mgr.get_service_health()
        self.assertFalse(health.is_running)
        self.assertIsNone(health.pid)


if __name__ == "__main__":
    unittest.main()
