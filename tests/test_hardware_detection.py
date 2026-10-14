"""Unit tests for hardware capability detection module."""

import os
import unittest

from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareDetector,
    InterfaceType,
)
from tests.mock_sysfs import MockSysfs


class TestHardwareDetection(unittest.TestCase):
    """Test suite for hardware detection with mocked sysfs interfaces."""

    def setUp(self):
        self.mock = MockSysfs()
        self.detector = HardwareDetector(
            sys_root=self.mock.sys_dir,
            proc_root=self.mock.proc_dir,
        )

    def tearDown(self):
        self.mock.cleanup()

    def test_ideapad_60_percent_detection(self):
        """Standard IdeaPad with 60% conservation limit."""
        self.mock.setup_dmi(
            vendor="LENOVO",
            product_name="81D2",
            product_version="Lenovo ideapad 330-15ARR",
            product_family="ideapad 330-15ARR",
        )
        self.mock.setup_battery("BAT0", capacity=65, status="Charging")
        self.mock.setup_ac_adapter("ADP0", online=1)
        cm_path = self.mock.setup_ideapad_conservation(initial_value=0)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.CONSERVATION_60)
        self.assertEqual(caps.interface_type, InterfaceType.IDEAPAD_CONSERVATION)
        self.assertTrue(caps.is_lenovo)
        self.assertEqual(caps.interface_path, cm_path)
        self.assertIn(ChargingProfile.CONSERVATION_60, caps.supported_profiles)
        self.assertIn(ChargingProfile.SMART_80, caps.supported_profiles)
        self.assertIn(ChargingProfile.FULL_CHARGE, caps.supported_profiles)
        self.assertEqual(len(caps.batteries), 1)
        self.assertTrue(caps.is_ac_online)

    def test_legion_80_percent_detection(self):
        """Legion / LOQ model with native 80% firmware threshold."""
        self.mock.setup_dmi(
            vendor="LENOVO",
            product_name="Legion 5 15ACH6H",
            product_version="Lenovo Legion 5 Pro",
            product_family="Legion 5",
        )
        self.mock.setup_battery("BAT0", capacity=78, status="Charging")
        self.mock.setup_ac_adapter("ADP0", online=1)
        cm_path = self.mock.setup_ideapad_conservation(initial_value=1)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.CONSERVATION_80)
        self.assertIn(ChargingProfile.CONSERVATION_80, caps.supported_profiles)
        self.assertIn(ChargingProfile.FULL_CHARGE, caps.supported_profiles)
        # Smart 80% must NOT be present on native 80% hardware
        self.assertNotIn(ChargingProfile.SMART_80, caps.supported_profiles)

    def test_thinkpad_configurable_thresholds_detection(self):
        """ThinkPad with configurable start and end charge thresholds."""
        self.mock.setup_dmi(
            vendor="LENOVO",
            product_name="20U9001RUS",
            product_version="ThinkPad X1 Carbon Gen 8",
            product_family="ThinkPad X1 Carbon",
        )
        self.mock.setup_thinkpad_thresholds(start_thresh=75, end_thresh=80)
        self.mock.setup_ac_adapter("AC", online=1)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.CONFIGURABLE_THRESHOLDS)
        self.assertEqual(caps.interface_type, InterfaceType.THINKPAD_THRESHOLDS)
        self.assertIn(ChargingProfile.CONFIGURABLE_80, caps.supported_profiles)
        self.assertIn(ChargingProfile.FULL_CHARGE, caps.supported_profiles)

    def test_dual_battery_thinkpad(self):
        """ThinkPad with dual batteries (BAT0 and BAT1)."""
        self.mock.setup_dmi(
            vendor="LENOVO",
            product_name="20L5000UUS",
            product_version="ThinkPad T480",
            product_family="ThinkPad T480",
        )
        self.mock.setup_battery("BAT0", capacity=80, start_threshold=75, end_threshold=80)
        self.mock.setup_battery("BAT1", capacity=50, start_threshold=75, end_threshold=80)
        self.mock.setup_ac_adapter("AC", online=1)
        self.mock.write_file("/sys/module/thinkpad_acpi/version", "1.0")
        os.makedirs(os.path.join(self.mock.root, "sys/bus/platform/drivers/thinkpad_acpi"), exist_ok=True)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.CONFIGURABLE_THRESHOLDS)
        self.assertEqual(len(caps.batteries), 2)

    def test_non_lenovo_hardware(self):
        """Non-Lenovo hardware (e.g. Dell XPS)."""
        self.mock.setup_dmi(
            vendor="Dell Inc.",
            product_name="XPS 15 9500",
            product_version="1.0",
            product_family="XPS",
        )
        self.mock.setup_battery("BAT0", capacity=90)
        self.mock.setup_ac_adapter("AC", online=1)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.NOT_SUPPORTED)
        self.assertFalse(caps.is_lenovo)
        self.assertEqual(len(caps.supported_profiles), 0)
        self.assertIn("Dell Inc.", caps.reason)

    def test_lenovo_without_conservation_interfaces(self):
        """Lenovo desktop or unsupported model lacking ACPI conservation_mode."""
        self.mock.setup_dmi(
            vendor="LENOVO",
            product_name="10AA",
            product_version="ThinkCentre M73",
            product_family="ThinkCentre",
        )
        self.mock.write_file("/sys/module/ideapad_laptop/version", "1.0")

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.NOT_SUPPORTED)
        self.assertTrue(caps.is_lenovo)
        self.assertEqual(len(caps.supported_profiles), 0)

    def test_missing_kernel_modules(self):
        """Lenovo laptop where neither ideapad_laptop nor thinkpad_acpi is loaded."""
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2")
        self.mock.setup_battery("BAT0", capacity=50)

        caps = self.detector.detect()
        self.assertEqual(caps.state, CapabilityState.UNABLE_TO_DETECT)
        self.assertIn("sudo modprobe", caps.reason)

    def test_missing_battery(self):
        """Laptop operating without a battery installed."""
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2")
        self.mock.setup_ac_adapter("ADP0", online=1)
        self.mock.setup_ideapad_conservation()

        caps = self.detector.detect()
        self.assertEqual(len(caps.batteries), 0)
        self.assertIsNone(caps.primary_battery)
        self.assertTrue(caps.is_ac_online)

    def test_ac_adapter_disconnection(self):
        """Detect AC adapter disconnected."""
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2")
        self.mock.setup_battery("BAT0", capacity=72, status="Discharging")
        self.mock.setup_ac_adapter("ADP0", online=0)
        self.mock.setup_ideapad_conservation()

        caps = self.detector.detect()
        self.assertFalse(caps.is_ac_online)
        self.assertEqual(caps.primary_battery.status, "Discharging")


if __name__ == "__main__":
    unittest.main()
