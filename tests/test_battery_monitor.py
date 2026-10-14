"""Unit tests for battery and AC monitor module."""

import time
import unittest

from lenovo_conservation.battery_monitor import BatteryMonitor, PowerSupplySnapshot
from lenovo_conservation.hardware_detection import HardwareDetector
from tests.mock_sysfs import MockSysfs


class TestBatteryMonitor(unittest.TestCase):
    """Test suite for BatteryMonitor updates and callbacks."""

    def setUp(self):
        self.mock = MockSysfs()
        self.mock.setup_dmi(vendor="LENOVO", product_name="81D2")
        self.mock.setup_battery("BAT0", capacity=70, status="Charging")
        self.mock.setup_ac_adapter("ADP0", online=1)
        self.detector = HardwareDetector(sys_root=self.mock.sys_dir, proc_root=self.mock.proc_dir)
        self.monitor = BatteryMonitor(
            detector=self.detector,
            poll_interval_ac=0.1,
            poll_interval_bat=0.1,
        )

    def tearDown(self):
        self.monitor.stop()
        self.mock.cleanup()

    def test_immediate_snapshot(self):
        """Read initial power supply snapshot."""
        snap = self.monitor.get_snapshot()
        self.assertEqual(snap.capacity, 70)
        self.assertEqual(snap.status, "Charging")
        self.assertTrue(snap.ac_online)

    def test_callback_dispatch(self):
        """Ensure callbacks receive power supply changes."""
        received_snapshots = []

        def callback(snapshot: PowerSupplySnapshot):
            received_snapshots.append(snapshot)

        self.monitor.add_callback(callback)
        self.monitor.start()

        # Update battery capacity in sysfs
        time.sleep(0.15)
        self.mock.setup_battery("BAT0", capacity=71, status="Charging")
        time.sleep(0.25)

        self.monitor.stop()
        self.assertGreaterEqual(len(received_snapshots), 1)
        latest = received_snapshots[-1]
        self.assertEqual(latest.capacity, 71)

    def test_battery_health_grading_and_metrics(self):
        """Test health grade classification and hardware metrics calculation."""
        from lenovo_conservation.hardware_detection import BatteryInfo

        # 1. Good health (80-100%)
        b_good = BatteryInfo(
            name="BAT0",
            path="/sys/class/power_supply/BAT0",
            energy_full_design=50_000_000,
            energy_full=45_000_000,
            energy_now=25_000_000,
            power_now=15_000_000,
            voltage_now=11_100_000,
            voltage_min_design=10_800_000,
        )
        self.assertEqual(b_good.design_capacity_wh, 50.0)
        self.assertEqual(b_good.full_charge_capacity_wh, 45.0)
        self.assertEqual(b_good.remaining_capacity_wh, 25.0)
        self.assertEqual(b_good.health_percent, 90.0)
        self.assertEqual(b_good.health_grade, "Good")
        self.assertEqual(b_good.power_rate_w, 15.0)
        self.assertEqual(b_good.voltage_v, 11.1)
        self.assertEqual(b_good.voltage_min_design_v, 10.8)

        # 2. Fair health (40-79%)
        b_fair = BatteryInfo(
            name="BAT0",
            path="/sys/class/power_supply/BAT0",
            energy_full_design=50_000_000,
            energy_full=30_000_000,
        )
        self.assertEqual(b_fair.health_percent, 60.0)
        self.assertEqual(b_fair.health_grade, "Fair")

        # 3. Critical health (<40%)
        b_crit = BatteryInfo(
            name="BAT0",
            path="/sys/class/power_supply/BAT0",
            energy_full_design=50_000_000,
            energy_full=15_000_000,
        )
        self.assertEqual(b_crit.health_percent, 30.0)
        self.assertEqual(b_crit.health_grade, "Critical")

        # Boundary checks
        b_80 = BatteryInfo(name="BAT0", path="", energy_full_design=100, energy_full=80)
        self.assertEqual(b_80.health_grade, "Good")

        b_79 = BatteryInfo(name="BAT0", path="", energy_full_design=100, energy_full=79)
        self.assertEqual(b_79.health_grade, "Fair")

        b_40 = BatteryInfo(name="BAT0", path="", energy_full_design=100, energy_full=40)
        self.assertEqual(b_40.health_grade, "Fair")

        b_39 = BatteryInfo(name="BAT0", path="", energy_full_design=100, energy_full=39)
        self.assertEqual(b_39.health_grade, "Critical")


if __name__ == "__main__":
    unittest.main()
