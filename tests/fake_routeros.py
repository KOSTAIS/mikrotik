"""In-memory stand-in for a librouteros connection."""

from __future__ import annotations

import copy
from typing import Any

from librouteros.exceptions import TrapError


def sample_router() -> dict[tuple[str, ...], list[dict[str, Any]]]:
    """A CAPsMAN controller (wifi package) with two CAPs and a guest SSID."""
    return {
        ("system", "identity"): [{"name": "home-router"}],
        ("system", "resource"): [
            {
                "uptime": "1w2d3h4m5s",
                "cpu-load": 7,
                "free-memory": 768 * 1024 * 1024,
                "total-memory": 1024 * 1024 * 1024,
                "version": "7.20 (stable)",
                "board-name": "hAP ax^3",
            }
        ],
        ("system", "routerboard"): [{"serial-number": "HG1234567", "model": "C53UiG+5HPaxD2HPaxD"}],
        ("interface",): [
            {".id": "*1", "name": "ether1", "type": "ether", "disabled": False, "running": True, "rx-byte": 1000, "tx-byte": 500},
            {".id": "*2", "name": "bridge", "type": "bridge", "disabled": False, "running": True, "rx-byte": 300, "tx-byte": 900},
            {".id": "*3", "name": "cap-wifi1", "type": "wifi", "disabled": False, "running": True, "rx-byte": 0, "tx-byte": 0},
            {".id": "*4", "name": "cap-wifi2", "type": "wifi", "disabled": False, "running": True, "rx-byte": 0, "tx-byte": 0},
            {".id": "*5", "name": "guest-24", "type": "wifi", "disabled": True, "running": False, "rx-byte": 0, "tx-byte": 0},
            {".id": "*6", "name": "guest-5", "type": "wifi", "disabled": True, "running": False, "rx-byte": 0, "tx-byte": 0},
        ],
        ("interface", "wifi"): [
            {".id": "*3", "name": "cap-wifi1", "configuration": "cfg-home", "disabled": False, "running": True},
            {".id": "*4", "name": "cap-wifi2", "configuration": "cfg-home", "disabled": False, "running": True},
            {".id": "*5", "name": "guest-24", "configuration": "cfg-guest", "disabled": True, "running": False},
            {".id": "*6", "name": "guest-5", "configuration.ssid": "Guest", "disabled": True, "running": False},
        ],
        ("interface", "wifi", "configuration"): [
            {".id": "*A", "name": "cfg-home", "ssid": "Home"},
            {".id": "*B", "name": "cfg-guest", "ssid": "Guest"},
        ],
        ("interface", "wifi", "registration-table"): [
            {".id": "*R1", "interface": "cap-wifi1"},
            {".id": "*R2", "interface": "cap-wifi1"},
            {".id": "*R3", "interface": "cap-wifi2"},
        ],
    }


class FakePath:
    def __init__(self, api: FakeApi, path: tuple[str, ...]) -> None:
        self.api = api
        self.path = path

    def _rows(self) -> list[dict[str, Any]]:
        if self.path not in self.api.menus:
            raise TrapError(message="no such command prefix")
        return self.api.menus[self.path]

    def __iter__(self):
        return iter(copy.deepcopy(self._rows()))

    def update(self, **kwargs: Any) -> None:
        self.api.calls.append((self.path, "set", kwargs))
        ids = str(kwargs[".id"]).split(",")
        for menu, rows in self.api.menus.items():
            # an interface lives in /interface and in its type menu
            if menu[0] != self.path[0]:
                continue
            for row in rows:
                if row.get(".id") in ids:
                    row.update({k: v for k, v in kwargs.items() if k != ".id"})


class FakeApi:
    def __init__(self, menus: dict[tuple[str, ...], list[dict[str, Any]]]) -> None:
        self.menus = menus
        self.calls: list[tuple] = []
        self.closed = False

    def path(self, *path: str) -> FakePath:
        return FakePath(self, tuple(path))

    def close(self) -> None:
        self.closed = True
