# SPDX-License-Identifier: GPL-3.0-or-later
"""Small persistent key/value store for wrapper state (port, window size, zoom).

Pat's own configuration is untouched and lives where Pat puts it.
"""

import json
import os

from gi.repository import GLib

_PATH = os.path.join(GLib.get_user_config_dir(), "pat-desktop", "state.json")
_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(_PATH) as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    data = _load()
    if data.get(key) == value:
        return
    data[key] = value
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _PATH)
