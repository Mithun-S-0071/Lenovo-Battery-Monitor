"""Hardware control module for Lenovo battery conservation.

Provides safe, verified reading and writing to sysfs attributes for
ideapad_acpi conservation_mode and thinkpad_acpi charge thresholds.
Enforces validation, idempotency, and post-write verification.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger("lenovo_conservation.control")


@dataclass
class ControlResult:
    """Result of a hardware control operation."""
    success: bool
    message: str
    previous_value: Any = None
    current_value: Any = None
    requires_elevation: bool = False
    details: Optional[dict] = None


class PrivilegedHelperProtocol(Protocol):
    """Protocol for privileged execution helpers."""
    def write_sysfs(self, path: str, value: str) -> ControlResult:
        ...


def read_attribute_value(path: str) -> Optional[str]:
    """Safely read the raw string content of a sysfs attribute."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except (OSError, IOError, PermissionError) as e:
        logger.warning("Failed to read sysfs attribute '%s': %s", path, e)
        return None


def read_attribute_int(path: str) -> Optional[int]:
    """Safely read an integer from a sysfs attribute."""
    val = read_attribute_value(path)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def write_sysfs_direct(path: str, value_str: str) -> tuple[bool, str]:
    """Attempt direct write to a sysfs file.

    Returns (success, error_message).
    """
    if not path or not os.path.isfile(path):
        return False, f"File not found: {path}"

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value_str)
            f.flush()
        return True, ""
    except PermissionError:
        return False, f"Permission denied writing to '{path}'. Root or helper privileges required."
    except (OSError, IOError) as e:
        return False, f"OS error writing to '{path}': {e}"


class LenovoHardwareController:
    """Controller for Lenovo charging limits with validation and verification."""

    def __init__(self, privileged_helper: Optional[PrivilegedHelperProtocol] = None):
        self.helper = privileged_helper

    def set_helper(self, helper: PrivilegedHelperProtocol) -> None:
        """Update the privileged helper reference."""
        self.helper = helper

    def get_conservation_mode(self, path: str) -> Optional[int]:
        """Read current conservation mode from sysfs (0 = disabled, 1 = enabled)."""
        return read_attribute_int(path)

    def set_conservation_mode(self, path: str, enable: bool) -> ControlResult:
        """Set ideapad_acpi conservation mode to enabled (1) or disabled (0).

        Applies strict validation, checks for idempotency, attempts direct write
        or falls back to privileged helper, and verifies the hardware state.
        """
        if not path or not os.path.isfile(path):
            return ControlResult(
                success=False,
                message=f"Conservation mode interface not found: {path}",
            )

        target_val = 1 if enable else 0
        target_str = str(target_val)
        mode_label = "enabled" if enable else "disabled"

        # Step 1: Idempotency check. Never write repeatedly if already in target state.
        prev_val = self.get_conservation_mode(path)
        if prev_val == target_val:
            return ControlResult(
                success=True,
                message=f"Conservation mode is already {mode_label}.",
                previous_value=prev_val,
                current_value=target_val,
            )

        # Step 2: Attempt direct write first (if process has permission)
        direct_ok, err_msg = write_sysfs_direct(path, target_str)

        if not direct_ok:
            # If permission denied and we have a privileged helper, delegate to helper
            if "Permission denied" in err_msg and self.helper is not None:
                logger.info("Direct write failed with permission denied; delegating to privileged helper")
                helper_res = self.helper.write_sysfs(path, target_str)
                if not helper_res.success:
                    return helper_res
            else:
                return ControlResult(
                    success=False,
                    message=err_msg,
                    previous_value=prev_val,
                    current_value=prev_val,
                    requires_elevation=("Permission denied" in err_msg),
                )

        # Step 3: Hardware verification. Read back to confirm firmware accepted write.
        time.sleep(0.05)  # Brief pause for ACPI/EC firmware update
        actual_val = self.get_conservation_mode(path)

        if actual_val == target_val:
            return ControlResult(
                success=True,
                message=f"Conservation mode successfully {mode_label}.",
                previous_value=prev_val,
                current_value=actual_val,
            )
        else:
            return ControlResult(
                success=False,
                message=(
                    f"Write succeeded but firmware state did not update "
                    f"(expected {target_val}, got {actual_val})."
                ),
                previous_value=prev_val,
                current_value=actual_val,
            )

    def get_thresholds(
        self, start_path: Optional[str], end_path: Optional[str]
    ) -> tuple[Optional[int], Optional[int]]:
        """Read start and end charge thresholds."""
        start_val = read_attribute_int(start_path) if start_path else None
        end_val = read_attribute_int(end_path) if end_path else None
        return start_val, end_val

    def set_thresholds(
        self,
        start_path: Optional[str],
        end_path: str,
        start_thresh: int,
        end_thresh: int,
    ) -> ControlResult:
        """Set ThinkPad battery charging start and end thresholds.

        Validates ranges (0 <= start < end <= 100), applies idempotency check,
        writes values, and verifies the hardware state.
        """
        # Validation
        if not (0 <= start_thresh <= 100):
            return ControlResult(
                success=False,
                message=f"Invalid start threshold: {start_thresh}. Must be between 0 and 100.",
            )
        if not (0 <= end_thresh <= 100):
            return ControlResult(
                success=False,
                message=f"Invalid end threshold: {end_thresh}. Must be between 0 and 100.",
            )
        if start_thresh >= end_thresh and end_thresh < 100:
            return ControlResult(
                success=False,
                message=f"Start threshold ({start_thresh}%) must be less than end threshold ({end_thresh}%).",
            )

        if not end_path or not os.path.isfile(end_path):
            return ControlResult(
                success=False,
                message=f"End threshold interface not found: {end_path}",
            )

        prev_start, prev_end = self.get_thresholds(start_path, end_path)

        if prev_start == start_thresh and prev_end == end_thresh:
            return ControlResult(
                success=True,
                message=f"Thresholds already set to start={start_thresh}%, end={end_thresh}%.",
                previous_value=(prev_start, prev_end),
                current_value=(start_thresh, end_thresh),
            )

        # In thinkpad_acpi, it is best practice to write end_threshold first if increasing,
        # or start_threshold first if decreasing, to ensure start < end at all intermediate states.
        writes: list[tuple[str, str]] = []
        if prev_end is not None and end_thresh > prev_end:
            writes.append((end_path, str(end_thresh)))
            if start_path and os.path.isfile(start_path):
                writes.append((start_path, str(start_thresh)))
        else:
            if start_path and os.path.isfile(start_path):
                writes.append((start_path, str(start_thresh)))
            writes.append((end_path, str(end_thresh)))

        for p, val_str in writes:
            ok, err_msg = write_sysfs_direct(p, val_str)
            if not ok:
                if "Permission denied" in err_msg and self.helper is not None:
                    helper_res = self.helper.write_sysfs(p, val_str)
                    if not helper_res.success:
                        return helper_res
                else:
                    return ControlResult(
                        success=False,
                        message=err_msg,
                        previous_value=(prev_start, prev_end),
                        requires_elevation=("Permission denied" in err_msg),
                    )

        time.sleep(0.05)
        cur_start, cur_end = self.get_thresholds(start_path, end_path)

        # Verify
        end_ok = (cur_end == end_thresh)
        start_ok = (cur_start == start_thresh) if start_path else True

        if end_ok and start_ok:
            return ControlResult(
                success=True,
                message=f"Charge thresholds successfully set to {start_thresh}% - {end_thresh}%.",
                previous_value=(prev_start, prev_end),
                current_value=(cur_start, cur_end),
            )
        else:
            return ControlResult(
                success=False,
                message=(
                    f"Threshold write succeeded but verification failed: "
                    f"expected ({start_thresh}, {end_thresh}), got ({cur_start}, {cur_end})."
                ),
                previous_value=(prev_start, prev_end),
                current_value=(cur_start, cur_end),
            )
