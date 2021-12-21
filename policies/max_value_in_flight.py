#!/usr/bin/env python3
"""A plugin which enforces a maximum total value in flight (being unvaulted).

It uses a fixed configuration:
    - Its datadir is set in the 'demo' directory.
    - The maximum value in flight enforced is 10btc.

It stores the in flight vaults info as "deposit outpoint", "value" pairs in a
JSON file at the root of its data directory.
"""

import json
import os
import sys


MAX_VALUE = 10 * 10 ** 8
DATADIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demo",
    "max_value_flight_datadir",
)
DATASTORE_FNAME = os.path.join(DATADIR, "datastore.json")
JSON_KEY = "in_flight"


def read_request():
    """Read a JSON request from stdin up to the '\n' delimiter."""
    buf = ""
    while len(buf) == 0 or buf[-1] != "\n":
        buf += sys.stdin.read()
    return json.loads(buf)


def update_in_flight(entries):
    with open(DATASTORE_FNAME, "w+") as f:
        f.write(json.dumps({JSON_KEY: entries}))


def maybe_create_data_dir():
    if not os.path.isdir(DATADIR):
        os.makedirs(DATADIR)
        update_in_flight({})


def recorded_attempts():
    """Read the current value in-flight from a text file in our datadir."""
    maybe_create_data_dir()
    with open(DATASTORE_FNAME, "r") as f:
        data_store = json.loads(f.read())
    return data_store[JSON_KEY]


if __name__ == "__main__":
    req = read_request()
    block_info = req["block_info"]
    maybe_create_data_dir()

    # First update the recorded attempts with the new and pass attempts.
    in_flight = recorded_attempts()
    for op in block_info["successful_attempts"] + block_info["revaulted_attempts"]:
        del in_flight[op]
    for v in block_info["new_attempts"]:
        in_flight[v["deposit_outpoint"]] = v["value"]
    update_in_flight(in_flight)

    # If we get above the threshold, revault everything that is currently in-flight.
    resp = {"revault": []}
    value_in_flight = sum([in_flight[k] for k in in_flight])
    if value_in_flight >= MAX_VALUE:
        resp["revault"] = list(in_flight.keys())

    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()
