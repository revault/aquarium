#!/usr/bin/env python3
"""A plugin which enforces a maximum total value per day.

It uses a fixed configuration:
    - Its datadir is set in the 'demo' directory.
    - The maximum value enforced is 50btc per day.

It simply stores a counter which is reset to 0 after 144 blocks (assumes no reorg).
"""

import json
import os
import sys


MAX_VALUE = 50 * 10 ** 8
DATADIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demo",
    "max_value_day_datadir",
)
DATASTORE_FNAME = os.path.join(DATADIR, "datastore.json")


def read_request():
    """Read a JSON request from stdin up to the '\n' delimiter."""
    buf = ""
    while len(buf) == 0 or buf[-1] != "\n":
        buf += sys.stdin.read()
    return json.loads(buf)


def update_counter(counter):
    data = json.loads(open(DATASTORE_FNAME, "r").read())
    data["counter"] = counter
    open(DATASTORE_FNAME, "w+").write(json.dumps(data))


def maybe_create_data_dir(block_height):
    if not os.path.isdir(DATADIR):
        os.makedirs(DATADIR)
        open(DATASTORE_FNAME, "w+").write(
            json.dumps({"counter": 0, "block_height": block_height})
        )


def current_data():
    with open(DATASTORE_FNAME, "r") as f:
        return json.loads(f.read())


if __name__ == "__main__":
    req = read_request()
    block_info = req["block_info"]
    maybe_create_data_dir(req["block_height"])
    data = current_data()

    counter = data["counter"]
    if req["block_height"] >= data["block_height"] + 144:
        counter = 0

    resp = {"revault": []}
    for v in block_info["new_attempts"]:
        # Revault everything that gets above the threshold, but only what gets
        # above it.
        # FIXME: should we revault everything that is in flight?
        if counter + v["value"] > MAX_VALUE:
            resp["revault"].append(v["deposit_outpoint"])
            continue
        counter += v["value"]
    update_counter(counter)

    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()
