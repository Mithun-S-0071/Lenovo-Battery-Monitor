"""Mock sysfs and proc environment generator for unit testing."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Optional


class MockSysfs:
    """Manages an isolated temporary directory tree mimicking Linux /sys and /proc."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="mock_sysfs_")
        self.sys_dir = os.path.join(self.root, "sys")
        self.proc_dir = os.path.join(self.root, "proc")
        os.makedirs(self.sys_dir, exist_ok=True)
        os.makedirs(self.proc_dir, exist_ok=True)

    def cleanup(self) -> None:
        """Remove temporary directory tree."""
        if os.path.exists(self.root):
            shutil.rmtree(self.root, ignore_errors=True)

    def write_file(self, rel_path: str, content: str, mode: int = 0o644) -> str:
        """Write a mock sysfs/proc file with specific permissions."""
        clean_rel = rel_path.lstrip("/")
        full_path = os.path.join(self.root, clean_rel)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(full_path, mode)
        return full_path

    def setup_dmi(
        self,
        vendor: str = "LENOVO",
        product_name: str = "81D2",
        product_version: str = "Lenovo ideapad 330-15ARR",
        product_family: str = "ideapad 330-15ARR",
        chassis_type: str = "10",
        bios_version: str = "7VCN49WW",
    ) -> None:
        """Setup DMI identity attributes in sysfs."""
        dmi_dir = "/sys/class/dmi/id"
        self.write_file(f"{dmi_dir}/sys_vendor", vendor)
        self.write_file(f"{dmi_dir}/product_name", product_name)
        self.write_file(f"{dmi_dir}/product_version", product_version)
        self.write_file(f"{dmi_dir}/product_family", product_family)
        self.write_file(f"{dmi_dir}/chassis_type", chassis_type)
        self.write_file(f"{dmi_dir}/bios_version", bios_version)
        self.write_file("/proc/version", "Linux version 7.2.9-arch1-1 (mock)")

    def setup_battery(
        self,
        name: str = "BAT0",
        capacity: int = 70,
        status: str = "Charging",
        present: int = 1,
        start_threshold: Optional[int] = None,
        end_threshold: Optional[int] = None,
    ) -> str:
        """Setup battery power_supply node."""
        base = f"/sys/class/power_supply/{name}"
        self.write_file(f"{base}/type", "Battery")
        self.write_file(f"{base}/present", str(present))
        self.write_file(f"{base}/capacity", str(capacity))
        self.write_file(f"{base}/status", status)

        if start_threshold is not None:
            self.write_file(f"{base}/charge_control_start_threshold", str(start_threshold))
        if end_threshold is not None:
            self.write_file(f"{base}/charge_control_end_threshold", str(end_threshold))

        return os.path.join(self.root, base.lstrip("/"))

    def setup_ac_adapter(self, name: str = "ADP0", online: int = 1) -> str:
        """Setup AC adapter power_supply node."""
        base = f"/sys/class/power_supply/{name}"
        self.write_file(f"{base}/type", "Mains")
        self.write_file(f"{base}/online", str(online))
        return os.path.join(self.root, base.lstrip("/"))

    def setup_ideapad_conservation(
        self,
        initial_value: int = 0,
        model: str = "VPC2004:00",
        writable: bool = True,
    ) -> str:
        """Setup ideapad_acpi platform driver with conservation_mode."""
        driver_dir = f"/sys/bus/platform/drivers/ideapad_acpi/{model}"
        os.makedirs(os.path.join(self.root, driver_dir.lstrip("/")), exist_ok=True)
        self.write_file("/sys/module/ideapad_laptop/version", "1.0")

        perm = 0o666 if writable else 0o444
        cm_path = f"{driver_dir}/conservation_mode"
        return self.write_file(cm_path, str(initial_value), mode=perm)

    def setup_thinkpad_thresholds(
        self,
        start_thresh: int = 75,
        end_thresh: int = 80,
        bat_name: str = "BAT0",
        writable: bool = True,
    ) -> tuple[str, str]:
        """Setup ThinkPad battery charge thresholds."""
        self.write_file("/sys/module/thinkpad_acpi/version", "1.0")
        os.makedirs(os.path.join(self.root, "sys/bus/platform/drivers/thinkpad_acpi"), exist_ok=True)

        base = f"/sys/class/power_supply/{bat_name}"
        self.write_file(f"{base}/type", "Battery")
        self.write_file(f"{base}/present", "1")
        self.write_file(f"{base}/capacity", "60")
        self.write_file(f"{base}/status", "Charging")

        perm = 0o666 if writable else 0o444
        p_start = self.write_file(f"{base}/charge_control_start_threshold", str(start_thresh), mode=perm)
        p_end = self.write_file(f"{base}/charge_control_end_threshold", str(end_thresh), mode=perm)
        return p_start, p_end
