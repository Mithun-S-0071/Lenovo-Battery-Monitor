# Lenovo Battery Monitor - Cross-Distribution Installation Guide

This guide provides system requirements and step-by-step instructions to install and run **Lenovo Battery Monitor** natively across major Linux distributions.

---

## Fast Track: Clone & Install (Recommended)

The simplest and quickest way to install is directly from the source repository:

```bash
git clone https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor.git
cd Lenovo-Battery-Monitor
./install.sh
```

- For full system-wide Polkit and systemd integration:
  ```bash
  sudo ./install.sh --system
  ```
- For user-local installation (no root needed):
  ```bash
  ./install.sh --user
  ```


## 1. Arch Based

### Prerequisites
Install PySide6 and Polkit:
```bash
sudo pacman -S python pyside6 polkit
```

### Installation Option A: Native Package (PKGBUILD)
```bash
cd packaging/arch
makepkg -si
```

### Installation Option B: 1-Click Installer Script
```bash
# User-local (no root needed):
./install.sh

# Or system-wide:
sudo ./install.sh --system
```

---

## 2. Fedora Based

### Prerequisites
Install Python 3, PySide6, and Polkit:
```bash
sudo dnf install python3 python3-pyside6 polkit
```

### Installation Option A: RPM Package
```bash
rpmbuild -ba packaging/rpm/lenovo-conservation.spec
sudo dnf install ~/rpmbuild/RPMS/noarch/lenovo-conservation-*.rpm
```

### Installation Option B: 1-Click Installer Script
```bash
# User-local:
./install.sh

# Or system-wide:
sudo ./install.sh --system
```

---

## 3. Debian Based

### Prerequisites
Install Python 3, PySide6 Widgets, and PolicyKit:
```bash
sudo apt update
sudo apt install python3 python3-pyside6.qtwidgets policykit-1
```

### Installation Option A: Debian Package (.deb)
```bash
sudo apt install debhelper dh-python python3-all python3-setuptools
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../lenovo-conservation_1.0.0-1_all.deb
```

### Installation Option B: 1-Click Installer Script
```bash
# User-local:
./install.sh

# Or system-wide:
sudo ./install.sh --system
```

---

## 4. openSUSE Tumbleweed & Leap

### Prerequisites
```bash
sudo zypper install python3 python3-pyside6 polkit
```

### Installation via Installer Script
```bash
./install.sh
```

---

## 5. Universal Python Wheel / pip Installation

Prebuilt wheels and source tarballs are provided in `release/dist/`:

```bash
pip install release/dist/lenovo_conservation-1.0.0-py3-none-any.whl
```

---

## Verifying Installation

Launch the application:
```bash
# Graphical Desktop Interface:
lenovo-battery-monitor

# Command Line Status Check:
lenovo-battery-monitor --status

# Hardware Detection & Probed Battery Metrics:
lenovo-battery-monitor --detect

# Full Diagnostics Report:
lenovo-battery-monitor --diagnostics
```

*(The `lenovo-conservation` command is preserved as a compatible symlink alias).*

---

## Uninstallation

To remove Lenovo Battery Monitor:
```bash
./uninstall.sh
```
