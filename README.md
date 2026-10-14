# Lenovo Battery Monitor

A modern, cross-distribution Linux desktop application and background service for managing battery charging thresholds, conservation modes, and real-time battery health on Lenovo laptops.

Supported Lenovo laptop families:
- **Lenovo IdeaPad** (IdeaPad 3, 5, 300-series, 500-series, Slim, Flex, Yoga IdeaPad)
- **Lenovo ThinkPad** (X1, T-series, P-series, E-series, L-series)
- **Lenovo IdeaPad Gaming**
- **Lenovo LOQ**
- **Lenovo Legion** (Legion 5, Legion 7, Legion Pro, Legion Slim, Y-series)

Works across major Linux distributions: **Arch Linux**, **SteamOS**, **Fedora**, **Ubuntu**, **Debian**, **openSUSE**, **Linux Mint**, and other systemd-based distributions.

---

## Key Features

- **Genuine Hardware Battery Health Probing (Not Simulated/Default Values)**:
  - Probes live hardware metrics from sysfs and kernel thermal monitors:
    - **Design Capacity** (Watt-hours)
    - **Full Charge Capacity** (Watt-hours)
    - **Remaining Capacity** (Watt-hours and %)
    - **Battery Health Percentage**: Calculated directly as $(\text{Full Charge Capacity} / \text{Design Capacity}) \times 100$.
    - **Standardized Health Grading**:
      - `80-100% - Good` (Green)
      - `40-79% - Fair` (Amber)
      - `Less than 40% - Critical` (Red)
    - **Battery Temperature**: Probed from battery thermal nodes, battery hwmon, or system thermal zones (`k10temp`, `coretemp`, `acpitz`).
    - **Power Rate**: Live charging or discharging rate in Watts.
    - **Voltage & Min Design Voltage**: Live cell voltage probed via sysfs.
    - **Cycle Count**: Hardware-reported charge cycles.
    - **Battery Chemistry & Model**: Manufacturer, model name, and technology (e.g. Li-poly).
- **Genuine Hardware Capability Detection**: Detects actual sysfs and ACPI driver nodes (`ideapad_acpi`, `thinkpad_acpi`, `power_supply/BAT*`). Never guesses or assumes all models support the same limits.
- **Native Firmware Limits**:
  - **Fixed 60% Conservation**: Hardware-enforced limit on IdeaPad models via `VPC2004` conservation mode.
  - **Fixed 80% Conservation**: Hardware-enforced limit on modern Legion and LOQ models.
  - **Configurable Thresholds**: Native hardware start (75%) and stop (80%) thresholds on ThinkPads.
- **Smart 80% Software Controller**:
  - Intended for laptops with a fixed 60% native limit that lack native 80% support.
  - Enables conservation mode when battery reaches **≥ 80%**.
  - Disables conservation mode to resume charging when battery falls to **≤ 75%**.
  - Built-in hysteresis prevents rapid toggling near threshold boundaries.
  - *Note: Smart 80% charging works only when the device is on. If the laptop is turned off, firmware default behavior applies.*
- **Security & Privilege Separation**:
  - The graphical application runs entirely as an unprivileged user.
  - Hardware writes are delegated to a narrowly scoped helper (`lenovo-conservation-helper`) authorized via **Polkit** (`pkexec`) or direct udev access.
- **Adaptive Desktop Integration**:
  - **KDE Plasma**: Native Breeze-inspired interface using system color palette and styling. Automatically integrates into KDE Kickoff application launcher.
  - **GNOME**: Native Adwaita-inspired card layout and typography.
  - Clean, high-contrast fallback for XFCE, Cinnamon, MATE, i3, Sway, and other environments.
- **Dual Monitoring Architecture**:
  - Kernel netlink uevents for immediate event-driven status updates.
  - Low-overhead adaptive polling fallback (10s on AC, 30s on battery).
- **Diagnostics & Safe Detection**:
  - Safe read-only detection mode (`--detect`) that inspects hardware and probes battery metrics without modifying settings.
  - Comprehensive diagnostic report generator with one-click clipboard export.

---

## Hardware Capability States

| Capability State | Hardware Family | Sysfs Interface | Supported Profiles |
| :--- | :--- | :--- | :--- |
| **60% Conservation Supported** | Lenovo IdeaPad, IdeaPad Gaming, older Legion (Y520/Y530/Y540) | `/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode` | `Conservation — 60%`, `Smart 80%`, `Full Charge` |
| **80% Conservation Supported** | Modern Lenovo Legion (Legion 5/7/Pro), Lenovo LOQ | `/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode` | `Conservation — 80%`, `Full Charge` |
| **Configurable Thresholds Supported** | Lenovo ThinkPad (X1, T, P, E, L series) | `/sys/class/power_supply/BAT*/charge_control_*_threshold` | `Native 80% Conservation`, `Full Charge` |
| **Battery Charge Control Supported — Threshold Unknown** | ThinkPad with partial driver support | `/sys/class/power_supply/BAT*/charge_control_end_threshold` | `Full Charge` |
| **Not Supported** | Non-Lenovo hardware or Lenovo desktops lacking battery conservation ACPI | None | None (Controls disabled, diagnostics report provided) |
| **Unable to Detect** | Permission denied or platform driver module unloaded | Inaccessible node | Safe fallback (Guidance to modprobe driver) |

---

## Installation

### Quick Clone & Install (Recommended)

Simply clone and run the installer:

```bash
git clone https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor.git
cd Lenovo-Battery-Monitor
./install.sh
```

- **Interactive / Standard**: `./install.sh` (checks dependencies, sets up desktop menu and icons)
- **System-Wide (Recommended for Polkit elevation & system service)**:
  ```bash
  sudo ./install.sh --system
  ```
- **User-Local (No root / sudo required)**:
  ```bash
  ./install.sh --user
  ```

To uninstall at any time:
```bash
./uninstall.sh
```

See [INSTALL.md](INSTALL.md) for full instructions covering native distribution packages (`.deb`, `.rpm`, `PKGBUILD`).

---

## Usage

### Graphical Interface

Launch from your desktop application menu under **Settings → Lenovo Battery Monitor** or via terminal:
```bash
lenovo-battery-monitor
# (The alias lenovo-conservation is also supported)
```

### Command Line Interface

```bash
# Safe hardware-detection-only mode with full probed battery metrics
lenovo-battery-monitor --detect

# View live battery percentage, health %, temperature, and active profile
lenovo-battery-monitor --status

# Generate comprehensive hardware, battery, and kernel diagnostics report
lenovo-battery-monitor --diagnostics

# Switch active charging profile from terminal
lenovo-battery-monitor --profile conservation_60
lenovo-battery-monitor --profile smart_80
lenovo-battery-monitor --profile full_charge

# Run the Smart 80% background daemon directly
lenovo-battery-monitor --daemon
```

---

## Background Service & systemd Integration

To enable the Smart 80% controller to run automatically in the background across system reboots:

### System-wide service
```bash
sudo systemctl enable --now lenovo-conservation.service
```

### User service (Rootless)
```bash
systemctl --user enable --now lenovo-conservation.service
```

---

## Testing

Run the automated test suite covering all hardware families, sysfs mocking, health grading, and hysteresis state machines:
```bash
python3 -m unittest discover -s tests
```

---

## License

This project is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**.
See [LICENSE](LICENSE) for details.
