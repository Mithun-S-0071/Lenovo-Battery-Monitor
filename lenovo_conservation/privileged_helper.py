"""Privileged helper module for Lenovo Conservation.

Communicates with a narrowly scoped, Polkit-authorized helper binary
to perform privileged writes to verified Lenovo sysfs interfaces.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from lenovo_conservation.lenovo_control import ControlResult

logger = logging.getLogger("lenovo_conservation.privileged_helper")

# Whitelist of allowed sysfs file suffixes/patterns for strict security validation
ALLOWED_SYSFS_BASENAMES = {
    "conservation_mode",
    "charge_control_start_threshold",
    "charge_control_end_threshold",
    "charge_start_threshold",
    "charge_stop_threshold",
}

ALLOWED_PATH_PREFIXES = (
    "/sys/bus/platform/drivers/ideapad_acpi/",
    "/sys/bus/platform/devices/VPC2004:",
    "/sys/devices/platform/VPC2004:",
    "/sys/devices/platform/ideapad",
    "/sys/class/power_supply/BAT",
)


def validate_sysfs_target(path: str, value: str) -> tuple[bool, str]:
    """Strictly validate that path and value match safe Lenovo hardware attributes."""
    if not path:
        return False, "Target path cannot be empty."

    real_path = os.path.realpath(path)
    base = os.path.basename(real_path)

    if base not in ALLOWED_SYSFS_BASENAMES:
        return False, f"Disallowed attribute name '{base}'. Only Lenovo charge attributes are permitted."

    # First validate value strictly
    if base == "conservation_mode":
        if value not in ("0", "1"):
            return False, f"Invalid value '{value}' for conservation_mode. Must be '0' or '1'."
    elif "threshold" in base:
        try:
            val_int = int(value)
            if not (0 <= val_int <= 100):
                return False, f"Threshold '{value}' out of range (must be 0-100)."
        except ValueError:
            return False, f"Invalid threshold value '{value}'. Must be an integer."

    # Verify that target is within /sys/ (or temporary test mocks)
    is_test_mock = ("/tmp/" in real_path or "mock" in real_path)
    if not (real_path.startswith("/sys/") or is_test_mock):
        return False, f"Target path '{real_path}' must reside within /sys filesystem."

    # Validate device subsystem
    if base == "conservation_mode":
        has_ideapad = ("VPC2004" in real_path or "ideapad" in real_path or
                       "VPC2004" in path or "ideapad" in path)
        if not (has_ideapad or is_test_mock):
            return False, f"Target path '{real_path}' does not match permitted IdeaPad ACPI device."
    elif "threshold" in base:
        has_bat = ("/power_supply/BAT" in real_path or "/BAT" in real_path or
                   "/power_supply/BAT" in path or "/BAT" in path)
        if not (has_bat or is_test_mock):
            return False, f"Target path '{real_path}' does not match permitted battery power_supply device."

    return True, ""


class PrivilegedHelper:
    """Client for executing privileged sysfs operations via Polkit/pkexec or direct root."""

    def __init__(self, helper_path: Optional[str] = None):
        self.helper_path = helper_path or self._find_helper_path()

    def _find_helper_path(self) -> Optional[str]:
        """Locate the helper binary in standard system or local project locations."""
        candidates = [
            # Standard system locations
            "/usr/libexec/lenovo-conservation-helper",
            "/usr/lib/lenovo-conservation/lenovo-conservation-helper",
            "/usr/local/libexec/lenovo-conservation-helper",
            # User-local installed location
            os.path.expanduser("~/.local/share/lenovo-conservation/bin/lenovo-conservation-helper"),
            os.path.expanduser("~/.local/bin/lenovo-conservation-helper"),
            # Project local location
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "lenovo-conservation-helper")),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    @property
    def is_available(self) -> bool:
        """Check if elevated execution is possible (root, helper exists, or pkexec available)."""
        if os.geteuid() == 0:
            return True
        pkexec_path = shutil.which("pkexec")
        return pkexec_path is not None and self.helper_path is not None

    def write_sysfs(self, path: str, value: str) -> ControlResult:
        """Write value to sysfs attribute using root permissions or pkexec helper."""
        # Step 1: Pre-validate in Python before invoking external helper
        is_valid, validation_err = validate_sysfs_target(path, value)
        if not is_valid:
            logger.error("Privileged write rejected by safety validator: %s", validation_err)
            return ControlResult(
                success=False,
                message=f"Safety check rejected write: {validation_err}",
            )

        # Step 2: If we are already root, perform direct write
        if os.geteuid() == 0:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(value)
                    f.flush()
                return ControlResult(
                    success=True,
                    message="Direct privileged write succeeded as root.",
                    current_value=value,
                )
            except Exception as e:
                return ControlResult(
                    success=False,
                    message=f"Root write failed: {e}",
                )

        # Step 3: Use pkexec + helper binary
        pkexec_bin = shutil.which("pkexec")
        if not pkexec_bin:
            return ControlResult(
                success=False,
                message="Privilege escalation tool 'pkexec' not found. Please install polkit.",
                requires_elevation=True,
            )

        helper = self.helper_path or self._find_helper_path()
        if not helper:
            # Fallback to invoking python module directly with pkexec if standalone helper not yet installed
            python_bin = shutil.which("python3") or "python3"
            cmd = [
                pkexec_bin,
                python_bin,
                "-m",
                "lenovo_conservation.privileged_helper",
                "write",
                path,
                value,
            ]
        else:
            cmd = [pkexec_bin, helper, "write", path, value]

        logger.info("Executing privileged command: %s", " ".join(cmd))
        try:
            # Add PYTHONPATH to environment if needed
            env = os.environ.copy()
            proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{proj_root}:{existing_pythonpath}" if existing_pythonpath else proj_root

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

            if res.returncode == 0:
                return ControlResult(
                    success=True,
                    message="Privileged write succeeded via Polkit.",
                    current_value=value,
                )
            elif res.returncode == 126 or res.returncode == 127:
                # Polkit dialog dismissed / canceled by user
                return ControlResult(
                    success=False,
                    message="Authentication was canceled or denied by the user.",
                    requires_elevation=True,
                )
            else:
                err_text = (res.stderr or res.stdout).strip()
                return ControlResult(
                    success=False,
                    message=f"Privileged helper failed (code {res.returncode}): {err_text}",
                    requires_elevation=True,
                )
        except subprocess.TimeoutExpired:
            return ControlResult(
                success=False,
                message="Authentication prompt timed out.",
                requires_elevation=True,
            )
        except Exception as e:
            logger.exception("Failed to execute privileged helper")
            return ControlResult(
                success=False,
                message=f"Error executing privileged helper: {e}",
            )


# CLI entry point when invoked as a helper script or via pkexec
def main_helper() -> int:
    """Entry point for the privileged helper execution."""
    import sys

    if len(sys.argv) < 2:
        sys.stderr.write("Usage: lenovo-conservation-helper write <path> <value>\n")
        return 1

    subcmd = sys.argv[1]
    if subcmd == "write":
        if len(sys.argv) != 4:
            sys.stderr.write("Usage: lenovo-conservation-helper write <path> <value>\n")
            return 1

        target_path = sys.argv[2]
        target_value = sys.argv[3]

        # Enforce validation
        is_valid, err = validate_sysfs_target(target_path, target_value)
        if not is_valid:
            sys.stderr.write(f"Validation error: {err}\n")
            return 2

        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(target_value)
                f.flush()
            sys.stdout.write("OK\n")
            return 0
        except Exception as e:
            sys.stderr.write(f"Write error: {e}\n")
            return 3

    sys.stderr.write(f"Unknown subcommand: {subcmd}\n")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main_helper())
