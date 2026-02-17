#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="hotspot-manager",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "PyGObject>=3.42.0",
    ],
    entry_points={
        "console_scripts": [
            "hotspot-manager=hotspot_manager.main:main",
            "hotspot-cli=hotspot_manager.cli:main",
        ],
    },
    data_files=[
        ("share/applications", ["data/hotspot-manager.desktop"]),
    ],
    python_requires=">=3.8",
    description="Concurrent WiFi and Hotspot Manager for Linux",
    author="Hotspot Manager Team",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: X11 Applications :: GTK",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Networking",
    ],
)
