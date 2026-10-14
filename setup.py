#!/usr/bin/env python3
from setuptools import find_packages, setup

setup(
    name="lenovo-conservation",
    version="1.0.0",
    description="Cross-Distribution Lenovo Battery Conservation App for Linux",
    author="Lenovo Conservation Contributors",
    packages=find_packages(),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "lenovo-battery-monitor = lenovo_conservation.main:main",
            "lenovo-conservation = lenovo_conservation.main:main",
            "lenovo-conservation-daemon = lenovo_conservation.service:main_service",
            "lenovo-conservation-helper = lenovo_conservation.privileged_helper:main_helper",
        ],
    },
    data_files=[
        ("share/applications", ["data/lenovo-conservation.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["data/icons/lenovo-conservation.svg"]),
        ("share/polkit-1/actions", ["data/org.lenovo.conservation.policy"]),
        ("lib/systemd/system", ["data/lenovo-conservation.service"]),
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX :: Linux",
    ],
)
