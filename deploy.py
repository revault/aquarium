#!/usr/bin/env python3

from concurrent import futures
from test_framework.bitcoind import BitcoinD
from test_framework.revault_network import RevaultNetwork
from test_framework.utils import (
    POSTGRES_USER,
    POSTGRES_PASS,
    POSTGRES_HOST,
    POSTGRES_IS_SETUP,
    EXECUTOR_WORKERS,
    LOG_LEVEL,
)

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback


BASE_DIR = os.getenv("BASE_DIR", os.path.abspath("demo"))
SRC_DIR = os.getenv("SRC_DIR", os.path.abspath("src"))
COORDINATORD_SRC_DIR = os.path.join(SRC_DIR, "coordinatord")
COSIGNERD_SRC_DIR = os.path.join(SRC_DIR, "cosignerd")
REVAULTD_SRC_DIR = os.path.join(SRC_DIR, "revaultd")
SHELL = os.getenv("SHELL", "bash")
COORDINATORD_VERSION = os.getenv("COORDINATORD_VERSION", "master")
COSIGNERD_VERSION = os.getenv("COSIGNERD_VERSION", "master")
REVAULTD_VERSION = os.getenv("REVAULTD_VERSION", "master")


# FIXME: use tmp
def bitcoind_dir():
    return os.path.join(BASE_DIR, "bitcoind")


def executor():
    return futures.ThreadPoolExecutor(
        max_workers=EXECUTOR_WORKERS, thread_name_prefix="revault-demo"
    )


def is_listening(host, port):
    """Check if a service is listening there."""
    s = socket.socket()
    try:
        s.connect((host, port))
        return True
    except socket.error:
        return False


def build_src(src_dir, version, git_url):
    if not os.path.isdir(src_dir):
        if not os.path.isdir(SRC_DIR):
            os.makedirs(SRC_DIR)
        subprocess.check_call(["git", "-C", f"{SRC_DIR}", "clone", git_url])

    subprocess.check_call(["git", "-C", f"{src_dir}", "checkout", version])
    subprocess.check_call(
        ["cargo", "build", "--manifest-path", f"{src_dir}/Cargo.toml"]
    )


def build_all_binaries():
    logging.info(
        f"Building coordinatord at '{COORDINATORD_VERSION}' in '{COORDINATORD_SRC_DIR}'"
    )
    build_src(
        COORDINATORD_SRC_DIR,
        COORDINATORD_VERSION,
        "https://github.com/revault/coordinatord",
    )

    logging.info(
        f"Building cosignerd at '{COSIGNERD_VERSION}' in '{COSIGNERD_SRC_DIR}'"
    )
    build_src(
        COSIGNERD_SRC_DIR, COSIGNERD_VERSION, "https://github.com/revault/cosignerd"
    )

    logging.info(f"Building cosignerd at '{REVAULTD_VERSION}' in '{REVAULTD_SRC_DIR}'")
    build_src(REVAULTD_SRC_DIR, REVAULTD_VERSION, "https://github.com/revault/revaultd")


def bitcoind():
    bitcoind = BitcoinD(bitcoin_dir=bitcoind_dir())
    bitcoind.startup()

    bitcoind.rpc.createwallet(bitcoind.rpc.wallet_name, False, False, "", False, True)

    while bitcoind.rpc.getbalance() < 50:
        bitcoind.rpc.generatetoaddress(1, bitcoind.rpc.getnewaddress())

    while bitcoind.rpc.getblockcount() <= 1:
        time.sleep(0.1)

    return bitcoind


def deploy(n_stks, n_mans, n_stkmans, csv):
    if not POSTGRES_IS_SETUP:
        logging.error("I need the Postgres environment variable to be set.")
        print("Example:")
        print(
            f'  POSTGRES_USER="revault_test" POSTGRES_PASS="revault_test" {sys.argv[0]}'
        )
        sys.exit(1)

    if not is_listening(POSTGRES_HOST, 5432):
        logging.error(f"No Postgre server listening on {POSTGRES_HOST}:5432.")
        print(
            f"A simple way to get started with one given your POSTGRES_PASS and POSTGRES_USER:"
        )
        print(
            f"    docker run --rm -d -p 5432:5432 --name postgres-coordinatord -e POSTGRES_PASSWORD={POSTGRES_PASS} -e POSTGRES_USER={POSTGRES_USER} -e POSTGRES_DB=coordinator_db postgres:alpine"
        )
        sys.exit(1)

    if os.path.isdir(BASE_DIR):
        logging.info("Base directory exists already")
        resp = input(f"Remove non-empty '{BASE_DIR}' and start fresh? (y/n)")
        if resp.lower() == "y":
            shutil.rmtree(BASE_DIR)
        else:
            logging.info("Exiting")
            sys.exit(1)

    logging.info("Checking the source directories..")
    build_all_binaries()

    logging.info("Setting up bitcoind")
    bd = bitcoind()

    # In any case cleanup bitcoind before exiting
    try:
        logging.info(
            f"Deploying a Revault network with {n_stks} only-stakeholders,"
            f" {n_mans} only-managers, {n_stkmans} both stakeholders and managers"
            f" and a CSV of {csv}"
        )
        revaultd_path = os.path.join(REVAULTD_SRC_DIR, "target", "debug", "revaultd")
        coordinatord_path = os.path.join(
            COORDINATORD_SRC_DIR, "target", "debug", "revault_coordinatord"
        )
        cosignerd_path = os.path.join(COSIGNERD_SRC_DIR, "target", "debug", "cosignerd")
        rn = RevaultNetwork(
            BASE_DIR,
            bd,
            executor(),
            revaultd_path,
            coordinatord_path,
            cosignerd_path,
            POSTGRES_USER,
            POSTGRES_PASS,
            POSTGRES_HOST,
        )
        rn.deploy(n_stks, n_mans, n_stkmans, csv)

        revault_cli = os.path.join(REVAULTD_SRC_DIR, "target", "debug", "revault-cli")
        aliases_file = os.path.join(BASE_DIR, "aliases.sh")
        with open(aliases_file, "w") as f:
            f.write('PS1="(Revault demo) $PS1"\n')  # It's a hack it shouldn't be there
            f.write(f"alias bd=\"bitcoind -datadir='{bd.bitcoin_dir}'\"\n")
            f.write(f"alias bcli=\"bitcoin-cli -datadir='{bd.bitcoin_dir}'\"\n")
            for i, stk in enumerate(rn.stk_wallets):
                f.write(f'alias stk{i}cli="{revault_cli} --conf {stk.conf_file}"\n')
                f.write(f'alias stk{i}d="{revaultd_path} --conf {stk.conf_file}"\n')
            for i, man in enumerate(rn.man_wallets):
                f.write(f'alias man{i}cli="{revault_cli} --conf {man.conf_file}"\n')
                f.write(f'alias man{i}d="{revaultd_path} --conf {man.conf_file}"\n')
            for i, stkman in enumerate(rn.man_wallets):
                f.write(
                    f'alias stkman{i}cli="{revault_cli} --conf {stkman.conf_file}"\n'
                )
                f.write(
                    f'alias stkman{i}d="{revaultd_path} --conf {stkman.conf_file}"\n'
                )

        with open(aliases_file, "r") as f:
            available_aliases = "".join(f.readlines()[1:])
        print("Dropping you into a shell. Exit to end the session.")
        print(f"Available aliases: \n{available_aliases}\n")
        # In any case clean up all daemons before exiting
        try:
            subprocess.call([SHELL, "--init-file", f"{aliases_file}", "-i"])
        except Exception as e:
            logging.error(f"Got error: '{str(e)}'")
            traceback.format_exc()
        finally:
            logging.info("Cleaning up Revault deployment")
            rn.cleanup()
    except Exception as e:
        logging.error(f"Got error: '{str(e)}'")
        traceback.format_exc()
    finally:
        logging.info("Cleaning up bitcoind")
        bd.cleanup()


def setup_logging():
    log_level = logging.INFO
    if LOG_LEVEL.lower() in ["debug", "info", "warning"]:
        log_level = LOG_LEVEL.upper()
    logging.basicConfig(level=log_level)

    # Much hacky, much fancy
    logging.addLevelName(
        logging.INFO, f"\033[1;34m{logging.getLevelName(logging.INFO)}\033[1;0m"
    )
    logging.addLevelName(
        logging.WARNING, f"\033[1;33m{logging.getLevelName(logging.WARNING)}\033[1;0m"
    )
    logging.addLevelName(
        logging.ERROR, f"\033[1;31m{logging.getLevelName(logging.ERROR)}\033[1;0m"
    )


if __name__ == "__main__":
    setup_logging()

    if len(sys.argv) < 2:
        print("Not enough arguments")
        sys.exit(1)

    if sys.argv[1] == "deploy":
        if len(sys.argv) < 6:
            print("Need number of stakeholders, managers and stakeholder-managers")
            sys.exit(1)
        deploy(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))
    else:
        print("Unknown command")
        sys.exit(1)
