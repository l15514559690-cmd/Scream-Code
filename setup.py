#!/usr/bin/env python3
"""setuptools 入口：单一全局命令 ``scream``（``pip install -e .``）。"""

from __future__ import annotations

from setuptools import find_packages, setup

setup(
    name='scream-code',
    version='0.1.0',
    description='尖叫 Code（Scream Code）Python 工作区 CLI',
    packages=find_packages(where='.', include=('src', 'src.*')),
    python_requires='>=3.10',
    entry_points={
        'console_scripts': [
            'scream=src.main:cli_entry',
            'scream-config=src.main:config_entry',
        ],
    },
)
