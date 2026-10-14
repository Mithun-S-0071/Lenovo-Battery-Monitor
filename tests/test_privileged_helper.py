"""Unit tests for privileged helper validation and security checks."""

import unittest

from lenovo_conservation.privileged_helper import (
    PrivilegedHelper,
    validate_sysfs_target,
)


class TestPrivilegedHelper(unittest.TestCase):
    """Test suite for privileged helper security validation."""

    def test_valid_ideapad_conservation_target(self):
        """Allow valid ideapad_acpi conservation_mode paths."""
        valid_paths = [
            "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode",
            "/sys/bus/platform/devices/VPC2004:00/conservation_mode",
            "/sys/devices/platform/VPC2004:00/conservation_mode",
        ]
        for p in valid_paths:
            ok, err = validate_sysfs_target(p, "1")
            self.assertTrue(ok, f"Failed for {p}: {err}")
            ok0, err0 = validate_sysfs_target(p, "0")
            self.assertTrue(ok0, f"Failed for {p}: {err0}")

    def test_invalid_conservation_mode_values(self):
        """Reject non-binary values for conservation_mode."""
        path = "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode"
        for bad_val in ["2", "-1", "yes", "true", ""]:
            ok, err = validate_sysfs_target(path, bad_val)
            self.assertFalse(ok)
            self.assertIn("Must be '0' or '1'", err)

    def test_valid_thinkpad_threshold_targets(self):
        """Allow valid ThinkPad battery threshold attributes."""
        valid_paths = [
            "/sys/class/power_supply/BAT0/charge_control_start_threshold",
            "/sys/class/power_supply/BAT0/charge_control_end_threshold",
            "/sys/class/power_supply/BAT1/charge_start_threshold",
            "/sys/class/power_supply/BAT1/charge_stop_threshold",
        ]
        for p in valid_paths:
            ok, err = validate_sysfs_target(p, "80")
            self.assertTrue(ok, f"Failed for {p}: {err}")

    def test_invalid_threshold_values(self):
        """Reject out-of-range or non-numeric thresholds."""
        path = "/sys/class/power_supply/BAT0/charge_control_end_threshold"
        for bad_val in ["-5", "105", "auto", ""]:
            ok, err = validate_sysfs_target(path, bad_val)
            self.assertFalse(ok)

    def test_arbitrary_file_rejection(self):
        """Disallow writes to non-whitelisted files."""
        dangerous_paths = [
            "/etc/passwd",
            "/etc/shadow",
            "/sys/power/state",
            "/sys/kernel/sysrq",
            "/dev/sda",
        ]
        for p in dangerous_paths:
            ok, err = validate_sysfs_target(p, "1")
            self.assertFalse(ok)
            self.assertIn("Disallowed attribute name", err)


if __name__ == "__main__":
    unittest.main()
