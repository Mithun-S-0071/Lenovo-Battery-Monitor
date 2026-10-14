"""Hardware and capability detection module for Lenovo Conservation.

Inspects DMI information, battery sysfs interfaces, ideapad_acpi, thinkpad_acpi,
and firmware-attributes to determine battery charge-control capabilities.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CapabilityState(str, Enum):
    """Firmware/hardware capability states as specified by design."""
    CONSERVATION_60 = "60% Conservation Supported"
    CONSERVATION_80 = "80% Conservation Supported"
    CONFIGURABLE_THRESHOLDS = "Configurable Thresholds Supported"
    THRESHOLD_UNKNOWN = "Battery Charge Control Supported — Threshold Unknown"
    NOT_SUPPORTED = "Not Supported"
    UNABLE_TO_DETECT = "Unable to Detect"


class ChargingProfile(str, Enum):
    """Available charging profiles."""
    CONSERVATION_60 = "conservation_60"
    SMART_80 = "smart_80"
    CONSERVATION_80 = "conservation_80"
    CONFIGURABLE_80 = "configurable_80"
    FULL_CHARGE = "full_charge"


class InterfaceType(str, Enum):
    """Type of hardware interface detected."""
    IDEAPAD_CONSERVATION = "ideapad_conservation"
    THINKPAD_THRESHOLDS = "thinkpad_thresholds"
    FIRMWARE_ATTRIBUTES = "firmware_attributes"
    NONE = "none"


@dataclass
class BatteryInfo:
    """Detailed information for a single battery."""
    name: str
    path: str
    present: bool = True
    status: str = "Unknown"
    capacity: int = 0
    charge_start_threshold: Optional[int] = None
    charge_end_threshold: Optional[int] = None
    charge_start_threshold_path: Optional[str] = None
    charge_end_threshold_path: Optional[str] = None
    start_threshold_writable: bool = False
    end_threshold_writable: bool = False
    energy_now: Optional[int] = None
    energy_full: Optional[int] = None
    energy_full_design: Optional[int] = None
    power_now: Optional[int] = None
    voltage_now: Optional[int] = None
    voltage_min_design: Optional[int] = None
    cycle_count: Optional[int] = None
    technology: str = "Unknown"
    manufacturer: str = "Unknown"
    model_name: str = "Unknown"
    serial_number: str = "Unknown"
    capacity_level: str = "Unknown"
    temperature_c: Optional[float] = None
    temperature_source: str = "Not reported by hardware"

    @property
    def design_capacity_wh(self) -> Optional[float]:
        """Design capacity in Watt-hours."""
        if self.energy_full_design:
            return round(self.energy_full_design / 1_000_000.0, 2)
        return None

    @property
    def full_charge_capacity_wh(self) -> Optional[float]:
        """Full charge capacity in Watt-hours."""
        if self.energy_full:
            return round(self.energy_full / 1_000_000.0, 2)
        return None

    @property
    def remaining_capacity_wh(self) -> Optional[float]:
        """Remaining capacity in Watt-hours."""
        if self.energy_now:
            return round(self.energy_now / 1_000_000.0, 2)
        return None

    @property
    def health_percent(self) -> Optional[float]:
        """Battery health percentage (Full Charge / Design Capacity * 100)."""
        if self.energy_full and self.energy_full_design and self.energy_full_design > 0:
            return round((self.energy_full / self.energy_full_design) * 100.0, 1)
        return None

    @property
    def health_grade(self) -> str:
        """Health grade classification: 80-100% Good, 40-79% Fair, <40% Critical."""
        pct = self.health_percent
        if pct is None:
            return "Unknown"
        if pct >= 80.0:
            return "Good"
        elif pct >= 40.0:
            return "Fair"
        else:
            return "Critical"

    @property
    def voltage_v(self) -> Optional[float]:
        """Current voltage in Volts."""
        if self.voltage_now:
            return round(self.voltage_now / 1_000_000.0, 2)
        return None

    @property
    def voltage_min_design_v(self) -> Optional[float]:
        """Minimum design voltage in Volts."""
        if self.voltage_min_design:
            return round(self.voltage_min_design / 1_000_000.0, 2)
        return None

    @property
    def power_rate_w(self) -> Optional[float]:
        """Current charging or discharging power rate in Watts."""
        if self.power_now is not None:
            return round(abs(self.power_now) / 1_000_000.0, 2)
        return None

    @property
    def temperature_f(self) -> Optional[float]:
        """Battery temperature in Fahrenheit."""
        if self.temperature_c is not None:
            return round((self.temperature_c * 9.0 / 5.0) + 32.0, 1)
        return None


@dataclass
class ACAdapterInfo:
    """Information for an AC power adapter."""
    name: str
    path: str
    online: bool = False


@dataclass
class HardwareCapabilities:
    """Summary of detected laptop hardware and battery control capability."""
    state: CapabilityState
    interface_type: InterfaceType
    interface_path: Optional[str] = None
    laptop_vendor: str = "Unknown"
    product_name: str = "Unknown"
    product_version: str = "Unknown"
    product_family: str = "Unknown"
    chassis_type: str = "Unknown"
    bios_version: str = "Unknown"
    kernel_version: str = "Unknown"
    is_lenovo: bool = False
    driver_name: Optional[str] = None
    can_read: bool = False
    can_write_direct: bool = False
    requires_elevation: bool = True
    reason: str = ""
    diagnostic_notes: List[str] = field(default_factory=list)
    supported_profiles: List[ChargingProfile] = field(default_factory=list)
    batteries: List[BatteryInfo] = field(default_factory=list)
    ac_adapters: List[ACAdapterInfo] = field(default_factory=list)

    @property
    def primary_battery(self) -> Optional[BatteryInfo]:
        """Return the primary active battery if present."""
        for bat in self.batteries:
            if bat.present:
                return bat
        return self.batteries[0] if self.batteries else None

    @property
    def is_ac_online(self) -> bool:
        """Return True if any AC adapter is connected/online."""
        return any(ac.online for ac in self.ac_adapters)


def read_sysfs_file(path: str, default: str = "") -> str:
    """Safely read and strip a sysfs file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except (OSError, IOError, PermissionError):
        return default


def read_sysfs_int(path: str, default: Optional[int] = None) -> Optional[int]:
    """Safely read an integer from a sysfs file."""
    content = read_sysfs_file(path)
    if not content:
        return default
    try:
        return int(content)
    except ValueError:
        return default


def is_writable(path: str) -> bool:
    """Check if the given path is writable by the current process."""
    return os.access(path, os.W_OK)


def is_readable(path: str) -> bool:
    """Check if the given path is readable by the current process."""
    return os.access(path, os.R_OK)


class HardwareDetector:
    """Detector for Lenovo laptop hardware capabilities and sysfs battery interfaces."""

    def __init__(self, sys_root: str = "/sys", proc_root: str = "/proc"):
        """Initialize detector with customizable root paths for testing/mocking."""
        self.sys_root = os.path.abspath(sys_root)
        self.proc_root = os.path.abspath(proc_root)

    def _path(self, relative_path: str) -> str:
        """Resolve a sysfs or proc path relative to configured root."""
        clean_rel = relative_path.lstrip("/")
        if clean_rel.startswith("sys/"):
            return os.path.join(self.sys_root, clean_rel[4:])
        if clean_rel.startswith("proc/"):
            return os.path.join(self.proc_root, clean_rel[5:])
        return os.path.join(self.sys_root, clean_rel)

    def get_dmi_info(self) -> Dict[str, str]:
        """Read system DMI information from sysfs."""
        dmi_dir = self._path("/sys/class/dmi/id")
        fields = [
            "sys_vendor",
            "product_name",
            "product_version",
            "product_family",
            "chassis_type",
            "bios_version",
            "bios_date",
        ]
        info: Dict[str, str] = {}
        for field_name in fields:
            p = os.path.join(dmi_dir, field_name)
            info[field_name] = read_sysfs_file(p, "Unknown")
        return info

    def get_kernel_version(self) -> str:
        """Read kernel version from /proc/version or os.uname."""
        proc_ver = self._path("/proc/version")
        val = read_sysfs_file(proc_ver)
        if val:
            parts = val.split()
            if len(parts) >= 3:
                return parts[2]
            return val
        try:
            return os.uname().release
        except Exception:
            return "Unknown"

    def scan_power_supplies(self) -> tuple[List[BatteryInfo], List[ACAdapterInfo]]:
        """Inspect /sys/class/power_supply/ for batteries and AC adapters."""
        power_supply_dir = self._path("/sys/class/power_supply")
        batteries: List[BatteryInfo] = []
        ac_adapters: List[ACAdapterInfo] = []

        if not os.path.isdir(power_supply_dir):
            return batteries, ac_adapters

        try:
            entries = sorted(os.listdir(power_supply_dir))
        except OSError:
            return batteries, ac_adapters

        for entry in entries:
            full_path = os.path.join(power_supply_dir, entry)
            # Resolve symlinks in case sysfs links to devices
            ps_type = read_sysfs_file(os.path.join(full_path, "type"))

            if ps_type == "Battery" or entry.startswith("BAT"):
                present_val = read_sysfs_int(os.path.join(full_path, "present"), 1)
                is_present = (present_val == 1)

                status = read_sysfs_file(os.path.join(full_path, "status"), "Unknown")
                capacity = read_sysfs_int(os.path.join(full_path, "capacity"), 0) or 0

                # Check for standard kernel 5.4+ charge control thresholds
                start_thresh_path = None
                end_thresh_path = None

                for start_candidate in [
                    "charge_control_start_threshold",
                    "charge_start_threshold",
                ]:
                    cand = os.path.join(full_path, start_candidate)
                    if os.path.exists(cand):
                        start_thresh_path = cand
                        break

                for end_candidate in [
                    "charge_control_end_threshold",
                    "charge_stop_threshold",
                ]:
                    cand = os.path.join(full_path, end_candidate)
                    if os.path.exists(cand):
                        end_thresh_path = cand
                        break

                start_thresh = read_sysfs_int(start_thresh_path) if start_thresh_path else None
                end_thresh = read_sysfs_int(end_thresh_path) if end_thresh_path else None

                start_writable = is_writable(start_thresh_path) if start_thresh_path else False
                end_writable = is_writable(end_thresh_path) if end_thresh_path else False

                voltage_now = read_sysfs_int(os.path.join(full_path, "voltage_now"))
                voltage_min_design = read_sysfs_int(os.path.join(full_path, "voltage_min_design"))
                v_scale = (voltage_min_design or voltage_now or 11100000) / 1_000_000.0

                energy_now = read_sysfs_int(os.path.join(full_path, "energy_now"))
                if energy_now is None:
                    charge_now = read_sysfs_int(os.path.join(full_path, "charge_now"))
                    if charge_now is not None:
                        energy_now = int(charge_now * v_scale)

                energy_full = read_sysfs_int(os.path.join(full_path, "energy_full"))
                if energy_full is None:
                    charge_full = read_sysfs_int(os.path.join(full_path, "charge_full"))
                    if charge_full is not None:
                        energy_full = int(charge_full * v_scale)

                energy_full_design = read_sysfs_int(os.path.join(full_path, "energy_full_design"))
                if energy_full_design is None:
                    charge_full_design = read_sysfs_int(os.path.join(full_path, "charge_full_design"))
                    if charge_full_design is not None:
                        energy_full_design = int(charge_full_design * v_scale)

                power_now = read_sysfs_int(os.path.join(full_path, "power_now"))
                if power_now is None:
                    current_now = read_sysfs_int(os.path.join(full_path, "current_now"))
                    if current_now is not None:
                        power_now = int(abs(current_now) * v_scale)

                cycle_count = read_sysfs_int(os.path.join(full_path, "cycle_count"))
                technology = read_sysfs_file(os.path.join(full_path, "technology"), "Unknown")
                manufacturer = read_sysfs_file(os.path.join(full_path, "manufacturer"), "Unknown")
                model_name = read_sysfs_file(os.path.join(full_path, "model_name"), "Unknown")
                serial_number = read_sysfs_file(os.path.join(full_path, "serial_number"), "Unknown")
                capacity_level = read_sysfs_file(os.path.join(full_path, "capacity_level"), "Unknown")

                temp_c, temp_source = self.probe_temperature(full_path)

                bat = BatteryInfo(
                    name=entry,
                    path=full_path,
                    present=is_present,
                    status=status,
                    capacity=capacity,
                    charge_start_threshold=start_thresh,
                    charge_end_threshold=end_thresh,
                    charge_start_threshold_path=start_thresh_path,
                    charge_end_threshold_path=end_thresh_path,
                    start_threshold_writable=start_writable,
                    end_threshold_writable=end_writable,
                    energy_now=energy_now,
                    energy_full=energy_full,
                    energy_full_design=energy_full_design,
                    power_now=power_now,
                    voltage_now=voltage_now,
                    voltage_min_design=voltage_min_design,
                    cycle_count=cycle_count,
                    technology=technology,
                    manufacturer=manufacturer,
                    model_name=model_name,
                    serial_number=serial_number,
                    capacity_level=capacity_level,
                    temperature_c=temp_c,
                    temperature_source=temp_source,
                )
                batteries.append(bat)

            elif ps_type in ("Mains", "USB", "USB_C", "USB_PD_CHARGER") or entry.startswith(("AC", "ADP")):
                online_val = read_sysfs_int(os.path.join(full_path, "online"), 0)
                ac = ACAdapterInfo(
                    name=entry,
                    path=full_path,
                    online=(online_val == 1),
                )
                ac_adapters.append(ac)

        return batteries, ac_adapters

    def probe_temperature(self, bat_path: str) -> tuple[Optional[float], str]:
        """Probe battery temperature from battery sysfs, hwmon, or system thermal zones."""
        # 1. Direct battery sysfs temp attribute
        temp_file = os.path.join(bat_path, "temp")
        if os.path.isfile(temp_file):
            raw = read_sysfs_int(temp_file)
            if raw is not None and raw > 0:
                if raw > 2000:
                    val = (raw - 2731) / 10.0
                elif raw > 100:
                    val = raw / 10.0
                else:
                    val = float(raw)
                return round(val, 1), "Battery Sensor"

        # 2. Battery hwmon directory inside battery or device
        for sub in ("hwmon", "device/hwmon"):
            device_hwmon = os.path.join(bat_path, sub)
            if os.path.isdir(device_hwmon):
                for hw in glob.glob(os.path.join(device_hwmon, "hwmon*")):
                    for t_in in glob.glob(os.path.join(hw, "temp*_input")):
                        raw = read_sysfs_int(t_in)
                        if raw is not None and raw > 0:
                            deg = raw / 1000.0 if raw > 1000 else float(raw)
                            return round(deg, 1), "Battery Hardware Monitor"

        # 3. Check any hwmon temp*_label specifically identifying battery
        hwmon_dir = self._path("/sys/class/hwmon")
        if os.path.isdir(hwmon_dir):
            for hw in sorted(glob.glob(os.path.join(hwmon_dir, "hwmon*"))):
                for lbl_file in sorted(glob.glob(os.path.join(hw, "temp*_label"))):
                    lbl_text = read_sysfs_file(lbl_file).lower()
                    if "bat" in lbl_text or "battery" in lbl_text:
                        in_file = lbl_file.replace("_label", "_input")
                        raw = read_sysfs_int(in_file)
                        if raw is not None and raw > 0:
                            deg = raw / 1000.0 if raw > 1000 else float(raw)
                            return round(deg, 1), "Battery Sensor"

        # Hardware does not report dedicated battery temperature
        return None, "N/A"

    def find_ideapad_conservation_path(self) -> Optional[str]:
        """Search known sysfs locations for ideapad_acpi conservation_mode."""
        candidate_patterns = [
            "/sys/bus/platform/drivers/ideapad_acpi/*/conservation_mode",
            "/sys/bus/platform/devices/VPC2004:*/conservation_mode",
            "/sys/devices/platform/VPC2004:*/conservation_mode",
            "/sys/devices/platform/ideapad_acpi.*/conservation_mode",
            "/sys/devices/platform/ideapad/conservation_mode",
        ]
        for pattern in candidate_patterns:
            resolved_pattern = self._path(pattern)
            matches = glob.glob(resolved_pattern)
            for match in matches:
                if os.path.isfile(match):
                    return match
        return None

    def is_module_loaded(self, module_name: str) -> bool:
        """Check if a kernel module is loaded via /sys/module or /proc/modules."""
        sys_mod = self._path(f"/sys/module/{module_name}")
        if os.path.isdir(sys_mod):
            return True

        proc_mods = self._path("/proc/modules")
        if os.path.isfile(proc_mods):
            try:
                with open(proc_mods, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith(f"{module_name} "):
                            return True
            except OSError:
                pass
        return False

    def is_driver_registered(self, driver_path_rel: str) -> bool:
        """Check if a platform driver directory exists."""
        full_p = self._path(driver_path_rel)
        return os.path.isdir(full_p)

    def _is_legion_or_loq_80(self, dmi: Dict[str, str]) -> bool:
        """Heuristic check if Legion/LOQ model natively enforces 80% limit in conservation mode."""
        combined = " ".join([
            dmi.get("product_name", ""),
            dmi.get("product_version", ""),
            dmi.get("product_family", ""),
        ]).lower()

        # Modern Legion models (e.g. Legion 5, Legion 7, Legion Pro, Legion Slim, LOQ 15, etc.)
        # typically enforce 80% in BIOS firmware. Older Y-series (Y520, Y530, Y540) use 60%.
        if "loq" in combined:
            return True
        if "legion pro" in combined or "legion 5" in combined or "legion 7" in combined or "legion 9" in combined:
            return True
        if "legion slim" in combined:
            return True
        return False

    def detect(self) -> HardwareCapabilities:
        """Perform comprehensive capability detection and return HardwareCapabilities."""
        dmi = self.get_dmi_info()
        kernel_ver = self.get_kernel_version()
        vendor = dmi.get("sys_vendor", "Unknown")
        prod_name = dmi.get("product_name", "Unknown")
        prod_ver = dmi.get("product_version", "Unknown")
        prod_fam = dmi.get("product_family", "Unknown")
        chassis = dmi.get("chassis_type", "Unknown")
        bios_ver = dmi.get("bios_version", "Unknown")

        is_lenovo = "lenovo" in vendor.lower()

        batteries, ac_adapters = self.scan_power_supplies()
        diag_notes: List[str] = []

        diag_notes.append(f"DMI: Vendor='{vendor}', Product='{prod_name}', Version='{prod_ver}', Family='{prod_fam}'")
        diag_notes.append(f"Kernel: {kernel_ver}")
        diag_notes.append(f"Batteries detected: {len(batteries)}; AC adapters: {len(ac_adapters)}")

        # Step 1: Check if vendor is Lenovo
        if not is_lenovo:
            return HardwareCapabilities(
                state=CapabilityState.NOT_SUPPORTED,
                interface_type=InterfaceType.NONE,
                laptop_vendor=vendor,
                product_name=prod_name,
                product_version=prod_ver,
                product_family=prod_fam,
                chassis_type=chassis,
                bios_version=bios_ver,
                kernel_version=kernel_ver,
                is_lenovo=False,
                reason=f"Device vendor '{vendor}' is not Lenovo. Hardware conservation controls are Lenovo-specific.",
                diagnostic_notes=diag_notes,
                supported_profiles=[],
                batteries=batteries,
                ac_adapters=ac_adapters,
            )

        # Step 2: Probe IdeaPad / Legion / LOQ conservation_mode
        ideapad_path = self.find_ideapad_conservation_path()
        ideapad_driver_loaded = self.is_driver_registered("/sys/bus/platform/drivers/ideapad_acpi")
        ideapad_mod_loaded = self.is_module_loaded("ideapad_laptop")

        diag_notes.append(
            f"IdeaPad ACPI driver: registered={ideapad_driver_loaded}, module_loaded={ideapad_mod_loaded}, path={ideapad_path}"
        )

        if ideapad_path:
            # Check read access
            if not is_readable(ideapad_path):
                # File exists but cannot even be read
                diag_notes.append(f"Permission denied reading '{ideapad_path}'")
                return HardwareCapabilities(
                    state=CapabilityState.UNABLE_TO_DETECT,
                    interface_type=InterfaceType.IDEAPAD_CONSERVATION,
                    interface_path=ideapad_path,
                    laptop_vendor=vendor,
                    product_name=prod_name,
                    product_version=prod_ver,
                    product_family=prod_fam,
                    chassis_type=chassis,
                    bios_version=bios_ver,
                    kernel_version=kernel_ver,
                    is_lenovo=True,
                    driver_name="ideapad_acpi",
                    can_read=False,
                    can_write_direct=False,
                    requires_elevation=True,
                    reason=f"Found interface '{ideapad_path}', but cannot read due to permission restrictions.",
                    diagnostic_notes=diag_notes,
                    supported_profiles=[],
                    batteries=batteries,
                    ac_adapters=ac_adapters,
                )

            current_val = read_sysfs_file(ideapad_path)
            diag_notes.append(f"conservation_mode read value: '{current_val}'")

            can_write_direct = is_writable(ideapad_path)
            requires_elev = not can_write_direct

            # Determine whether this is a native 80% (Legion/LOQ) or native 60% (IdeaPad)
            if self._is_legion_or_loq_80(dmi):
                state = CapabilityState.CONSERVATION_80
                supported_profiles = [
                    ChargingProfile.CONSERVATION_80,
                    ChargingProfile.FULL_CHARGE,
                ]
                diag_notes.append("Heuristic matched Legion/LOQ 80% firmware threshold profile.")
            else:
                state = CapabilityState.CONSERVATION_60
                supported_profiles = [
                    ChargingProfile.CONSERVATION_60,
                    ChargingProfile.SMART_80,
                    ChargingProfile.FULL_CHARGE,
                ]
                diag_notes.append("Standard IdeaPad 60% firmware threshold profile with Smart 80% support.")

            return HardwareCapabilities(
                state=state,
                interface_type=InterfaceType.IDEAPAD_CONSERVATION,
                interface_path=ideapad_path,
                laptop_vendor=vendor,
                product_name=prod_name,
                product_version=prod_ver,
                product_family=prod_fam,
                chassis_type=chassis,
                bios_version=bios_ver,
                kernel_version=kernel_ver,
                is_lenovo=True,
                driver_name="ideapad_acpi",
                can_read=True,
                can_write_direct=can_write_direct,
                requires_elevation=requires_elev,
                reason=f"Found IdeaPad conservation interface at '{ideapad_path}'.",
                diagnostic_notes=diag_notes,
                supported_profiles=supported_profiles,
                batteries=batteries,
                ac_adapters=ac_adapters,
            )

        # Step 3: Probe ThinkPad configurable battery thresholds
        thinkpad_driver_loaded = self.is_driver_registered("/sys/bus/platform/drivers/thinkpad_acpi")
        thinkpad_mod_loaded = self.is_module_loaded("thinkpad_acpi")
        diag_notes.append(
            f"ThinkPad ACPI driver: registered={thinkpad_driver_loaded}, module_loaded={thinkpad_mod_loaded}"
        )

        has_configurable_thresholds = False
        has_end_threshold_only = False
        tp_battery_path: Optional[str] = None

        for bat in batteries:
            if bat.charge_start_threshold_path and bat.charge_end_threshold_path:
                has_configurable_thresholds = True
                tp_battery_path = bat.charge_end_threshold_path
                break
            elif bat.charge_end_threshold_path:
                has_end_threshold_only = True
                tp_battery_path = bat.charge_end_threshold_path

        if has_configurable_thresholds and tp_battery_path:
            can_read = is_readable(tp_battery_path)
            can_write_direct = is_writable(tp_battery_path)
            supported_profiles = [
                ChargingProfile.CONFIGURABLE_80,
                ChargingProfile.FULL_CHARGE,
            ]
            return HardwareCapabilities(
                state=CapabilityState.CONFIGURABLE_THRESHOLDS,
                interface_type=InterfaceType.THINKPAD_THRESHOLDS,
                interface_path=tp_battery_path,
                laptop_vendor=vendor,
                product_name=prod_name,
                product_version=prod_ver,
                product_family=prod_fam,
                chassis_type=chassis,
                bios_version=bios_ver,
                kernel_version=kernel_ver,
                is_lenovo=True,
                driver_name="thinkpad_acpi",
                can_read=can_read,
                can_write_direct=can_write_direct,
                requires_elevation=not can_write_direct,
                reason="Found configurable battery start and end charge thresholds in sysfs.",
                diagnostic_notes=diag_notes,
                supported_profiles=supported_profiles,
                batteries=batteries,
                ac_adapters=ac_adapters,
            )

        if has_end_threshold_only and tp_battery_path:
            can_read = is_readable(tp_battery_path)
            can_write_direct = is_writable(tp_battery_path)
            return HardwareCapabilities(
                state=CapabilityState.THRESHOLD_UNKNOWN,
                interface_type=InterfaceType.THINKPAD_THRESHOLDS,
                interface_path=tp_battery_path,
                laptop_vendor=vendor,
                product_name=prod_name,
                product_version=prod_ver,
                product_family=prod_fam,
                chassis_type=chassis,
                bios_version=bios_ver,
                kernel_version=kernel_ver,
                is_lenovo=True,
                driver_name="thinkpad_acpi",
                can_read=can_read,
                can_write_direct=can_write_direct,
                requires_elevation=not can_write_direct,
                reason="Battery end charge threshold attribute found, but start threshold is not exposed.",
                diagnostic_notes=diag_notes,
                supported_profiles=[ChargingProfile.FULL_CHARGE],
                batteries=batteries,
                ac_adapters=ac_adapters,
            )

        # Step 4: No supported interface found. Diagnose why!
        # Check if modules are missing vs hardware unsupported
        if not ideapad_mod_loaded and not thinkpad_mod_loaded:
            diag_notes.append("Neither ideapad_laptop nor thinkpad_acpi kernel module is currently loaded.")
            reason = (
                "Neither 'ideapad_laptop' nor 'thinkpad_acpi' kernel module is loaded. "
                "Try running: 'sudo modprobe ideapad_laptop' or 'sudo modprobe thinkpad_acpi'."
            )
            return HardwareCapabilities(
                state=CapabilityState.UNABLE_TO_DETECT,
                interface_type=InterfaceType.NONE,
                laptop_vendor=vendor,
                product_name=prod_name,
                product_version=prod_ver,
                product_family=prod_fam,
                chassis_type=chassis,
                bios_version=bios_ver,
                kernel_version=kernel_ver,
                is_lenovo=True,
                reason=reason,
                diagnostic_notes=diag_notes,
                supported_profiles=[],
                batteries=batteries,
                ac_adapters=ac_adapters,
            )

        # Modules were loaded, but no device node exists
        reason = (
            "Lenovo device detected and drivers are loaded, but ACPI conservation mode "
            "or charge threshold sysfs attributes are not exposed by the hardware firmware."
        )
        return HardwareCapabilities(
            state=CapabilityState.NOT_SUPPORTED,
            interface_type=InterfaceType.NONE,
            laptop_vendor=vendor,
            product_name=prod_name,
            product_version=prod_ver,
            product_family=prod_fam,
            chassis_type=chassis,
            bios_version=bios_ver,
            kernel_version=kernel_ver,
            is_lenovo=True,
            reason=reason,
            diagnostic_notes=diag_notes,
            supported_profiles=[],
            batteries=batteries,
            ac_adapters=ac_adapters,
        )
