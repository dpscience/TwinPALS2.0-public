# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Keep long CeBr3 transport out of routine development/release checks."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-cebr3", action="store_true", default=False,
                     help="Explicitly include slow CeBr3 optical simulations")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-cebr3"):
        return
    excluded = pytest.mark.skip(reason="CeBr3 transport is opt-in: --run-cebr3")
    for item in items:
        if item.get_closest_marker("slow_cebr3"):
            item.add_marker(excluded)
