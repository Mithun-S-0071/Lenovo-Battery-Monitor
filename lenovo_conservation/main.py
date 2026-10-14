"""Main entry point for Lenovo Conservation application.

Supports GUI mode (PySide6), safe hardware-detection-only mode (--detect),
full diagnostic reporting (--diagnostics), and CLI profile switching (--profile).
"""

from __future__ import annotations

import argparse
import os
import sys

from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareCapabilities,
    HardwareDetector,
)
from lenovo_conservation.profile_manager import ProfileManager


def run_detect_only(detector: HardwareDetector) -> int:
    """Safe hardware-detection-only mode that cannot modify charging settings."""
    caps = detector.detect()
    print("==================================================")
    print("      LENOVO BATTERY MONITOR HARDWARE DETECTION   ")
    print("==================================================")
    print(f"Manufacturer / Vendor: {caps.laptop_vendor}")
    print(f"Product Model:         {caps.product_version or caps.product_name}")
    print(f"Chassis Type:          {caps.chassis_type}")
    print(f"Kernel Version:        {caps.kernel_version}")
    print(f"Driver Name:           {caps.driver_name or 'None'}")
    print("--------------------------------------------------")
    print(f"Capability State:      {caps.state.value}")
    print(f"Interface Type:        {caps.interface_type.value}")
    print(f"Interface Path:        {caps.interface_path or 'None'}")
    print(f"Direct Sysfs Writable: {caps.can_write_direct}")
    print(f"Requires Elevation:    {caps.requires_elevation}")
    print("--------------------------------------------------")
    print("Supported Profiles:")
    for prof in caps.supported_profiles:
        print(f"  • {prof.value}")
    if not caps.supported_profiles:
        print("  (None - charging limit unsupported on this device)")
    print("--------------------------------------------------")
    print("Probed Battery Details:")
    bats, _ = detector.scan_power_supplies()
    for b in bats:
        print(f"  • {b.name} ({b.manufacturer} {b.model_name}):")
        print(f"      Charge:          {b.capacity}% ({b.status})")
        if b.health_percent is not None:
            print(f"      Health:          {b.health_percent}% ({b.health_grade})")
        if b.design_capacity_wh:
            print(f"      Design Capacity: {b.design_capacity_wh} Wh")
        if b.full_charge_capacity_wh:
            print(f"      Full Charge Cap: {b.full_charge_capacity_wh} Wh")
        if b.remaining_capacity_wh:
            print(f"      Remaining Cap:   {b.remaining_capacity_wh} Wh")
        if b.temperature_c is not None:
            print(f"      Temperature:     {b.temperature_c} °C ({b.temperature_source})")
        if b.power_rate_w is not None:
            print(f"      Power Rate:      {b.power_rate_w} W")
        if b.voltage_v is not None:
            print(f"      Voltage:         {b.voltage_v} V")
        if b.cycle_count is not None:
            print(f"      Cycle Count:     {b.cycle_count}")
    print("--------------------------------------------------")
    print(f"Diagnostics:           {caps.reason}")
    print("==================================================")
    return 0


def run_diagnostics_report(mgr: ProfileManager) -> int:
    """Print complete diagnostic report."""
    from lenovo_conservation.ui.diagnostics_dialog import generate_diagnostic_report
    print(generate_diagnostic_report(mgr))
    return 0


def run_status(mgr: ProfileManager) -> int:
    """Print current battery, AC, and profile status."""
    caps = mgr.caps
    snap = mgr.monitor.get_snapshot()
    active_prof = mgr.get_active_profile()
    health = mgr.get_service_health()
    bat = snap.primary_battery

    print(f"Laptop Model:     {caps.laptop_vendor} {caps.product_version or caps.product_name}")
    print(f"Capability:       {caps.state.value}")
    print(f"Active Profile:   {active_prof.value}")
    print(f"Battery Capacity: {snap.capacity}% ({snap.status})")
    if bat:
        health_str = f"{bat.health_percent}% ({bat.health_grade})" if bat.health_percent is not None else "N/A"
        print(f"Battery Health:   {health_str}")
        if bat.design_capacity_wh:
            print(f"Design Capacity:  {bat.design_capacity_wh} Wh")
        if bat.full_charge_capacity_wh:
            print(f"Full Charge Cap:  {bat.full_charge_capacity_wh} Wh")
        if bat.remaining_capacity_wh:
            print(f"Remaining Cap:    {bat.remaining_capacity_wh} Wh")
        if bat.temperature_c is not None:
            print(f"Temperature:      {bat.temperature_c} °C ({bat.temperature_source})")
        if bat.power_rate_w is not None:
            print(f"Power Rate:       {bat.power_rate_w} W")
    print(f"AC Connected:     {snap.ac_online}")
    print(f"Daemon Running:   {health.is_running} (PID: {health.pid or 'N/A'})")
    if health.state.last_action:
        print(f"Last Action:      {health.state.last_action}")
    return 0


def run_gui(mgr: ProfileManager) -> int:
    """Launch the PySide6 desktop graphical interface."""
    # Check if graphical display is available
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        sys.stderr.write(
            "Error: No graphical display environment (DISPLAY or WAYLAND_DISPLAY) found.\n"
            "Use '--detect', '--status', or '--profile <name>' in terminal/headless environments.\n"
        )
        return 1

    try:
        from PySide6.QtWidgets import QApplication
        from lenovo_conservation.ui.main_window import MainWindow
    except ImportError as e:
        sys.stderr.write(
            f"Error: PySide6 is required for the graphical interface ({e}).\n"
            "Please install PySide6 or use the command line flags: --detect, --status, --profile\n"
        )
        return 1

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Lenovo Battery Monitor")
    app.setApplicationDisplayName("Lenovo Battery Monitor")
    app.setOrganizationName("Lenovo")

    window = MainWindow(profile_mgr=mgr)
    window.show()

    return app.exec()


def main() -> int:
    """Application main entry point."""
    parser = argparse.ArgumentParser(
        description="Lenovo Battery Monitor - Battery Conservation & Hardware Health Monitor for Linux"
    )
    parser.add_argument(
        "--detect", "-d",
        action="store_true",
        help="Safe hardware-detection-only mode (read-only, does not modify charging settings)",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Generate and print comprehensive hardware and kernel diagnostics report",
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Display current battery, AC power, and active profile status",
    )
    parser.add_argument(
        "--profile", "-p",
        choices=[p.value for p in ChargingProfile],
        help="Switch active charging profile via command line",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run background Smart 80%% service daemon",
    )

    args = parser.parse_args()

    # Safe detection mode
    if args.detect:
        return run_detect_only(HardwareDetector())

    # Background service daemon
    if args.daemon:
        from lenovo_conservation.service import LenovoConservationService
        svc = LenovoConservationService()
        svc.run_daemon()
        return 0

    mgr = ProfileManager()

    # Diagnostics report
    if args.diagnostics:
        return run_diagnostics_report(mgr)

    # Status check
    if args.status:
        return run_status(mgr)

    # CLI profile switch
    if args.profile:
        target = ChargingProfile(args.profile)
        res = mgr.apply_profile(target)
        if res.success:
            print(f"Success: {res.message}")
            return 0
        else:
            sys.stderr.write(f"Error: {res.message}\n")
            return 1

    # Default: launch GUI
    return run_gui(mgr)


if __name__ == "__main__":
    sys.exit(main())
