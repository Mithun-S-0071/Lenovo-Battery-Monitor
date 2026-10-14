"""Unit tests for Lenovo hardware control module."""

import os
import unittest

from lenovo_conservation.lenovo_control import (
    ControlResult,
    LenovoHardwareController,
    read_attribute_int,
    read_attribute_value,
    write_sysfs_direct,
)
from tests.mock_sysfs import MockSysfs


class TestLenovoControl(unittest.TestCase):
    """Test suite for safe hardware sysfs read/write and validation."""

    def setUp(self):
        self.mock = MockSysfs()
        self.ctrl = LenovoHardwareController()

    def tearDown(self):
        self.mock.cleanup()

    def test_read_conservation_mode(self):
        """Read conservation_mode integer."""
        cm_path = self.mock.setup_ideapad_conservation(initial_value=1)
        val = self.ctrl.get_conservation_mode(cm_path)
        self.assertEqual(val, 1)

    def test_set_conservation_mode_enable(self):
        """Enable conservation mode with verification."""
        cm_path = self.mock.setup_ideapad_conservation(initial_value=0)
        res = self.ctrl.set_conservation_mode(cm_path, enable=True)
        self.assertTrue(res.success)
        self.assertEqual(res.current_value, 1)
        self.assertEqual(self.ctrl.get_conservation_mode(cm_path), 1)

    def test_set_conservation_mode_disable(self):
        """Disable conservation mode (Full Charge)."""
        cm_path = self.mock.setup_ideapad_conservation(initial_value=1)
        res = self.ctrl.set_conservation_mode(cm_path, enable=False)
        self.assertTrue(res.success)
        self.assertEqual(res.current_value, 0)
        self.assertEqual(self.ctrl.get_conservation_mode(cm_path), 0)

    def test_idempotent_conservation_write(self):
        """Ensure unnecessary repeated writes are avoided."""
        cm_path = self.mock.setup_ideapad_conservation(initial_value=1)
        res = self.ctrl.set_conservation_mode(cm_path, enable=True)
        self.assertTrue(res.success)
        self.assertIn("already enabled", res.message)

    def test_set_thinkpad_thresholds_valid(self):
        """Set ThinkPad thresholds with verification."""
        p_start, p_end = self.mock.setup_thinkpad_thresholds(start_thresh=50, end_thresh=60)
        res = self.ctrl.set_thresholds(p_start, p_end, start_thresh=75, end_thresh=80)
        self.assertTrue(res.success)
        cur_start, cur_end = self.ctrl.get_thresholds(p_start, p_end)
        self.assertEqual(cur_start, 75)
        self.assertEqual(cur_end, 80)

    def test_thinkpad_thresholds_invalid_range(self):
        """Reject invalid threshold percentages."""
        p_start, p_end = self.mock.setup_thinkpad_thresholds(start_thresh=75, end_thresh=80)

        # start >= end
        res = self.ctrl.set_thresholds(p_start, p_end, start_thresh=85, end_thresh=80)
        self.assertFalse(res.success)
        self.assertIn("must be less than", res.message)

        # out of range (> 100)
        res2 = self.ctrl.set_thresholds(p_start, p_end, start_thresh=-5, end_thresh=80)
        self.assertFalse(res2.success)

    def test_permission_denied_handling(self):
        """Read-only sysfs file handles write failure gracefully."""
        cm_path = self.mock.setup_ideapad_conservation(initial_value=0, writable=False)
        # Attempt to write to read-only file
        res = self.ctrl.set_conservation_mode(cm_path, enable=True)
        self.assertFalse(res.success)
        self.assertTrue(res.requires_elevation)


if __name__ == "__main__":
    unittest.main()
