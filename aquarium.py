#!/usr/bin/env python3
import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import test_framework
import time
import traceback

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
    DEBUG_GUI,
    REVAULTD_PATH,
)


BASE_DIR = os.getenv("BASE_DIR", os.path.abspath("demo"))
SRC_DIR = os.getenv("SRC_DIR", os.path.abspath("src"))
COORDINATORD_SRC_DIR = os.path.join(SRC_DIR, "coordinatord")
COSIGNERD_SRC_DIR = os.path.join(SRC_DIR, "cosignerd")
MIRADORD_SRC_DIR = os.path.join(SRC_DIR, "miradord")
REVAULTD_SRC_DIR = os.path.join(SRC_DIR, "revaultd")
REVAULT_GUI_SRC_DIR = os.path.join(SRC_DIR, "revault-gui")
SHELL = os.getenv("SHELL", "bash")
COORDINATORD_VERSION = os.getenv("COORDINATORD_VERSION", "master")
COSIGNERD_VERSION = os.getenv("COSIGNERD_VERSION", "master")
MIRADORD_VERSION = os.getenv("MIRADORD_VERSION", "master")
REVAULTD_VERSION = os.getenv("REVAULTD_VERSION", "master")
REVAULT_GUI_VERSION = os.getenv("REVAULT_GUI_VERSION", "master")
WITH_GUI = os.getenv("WITH_GUI", "1") == "1"
WITH_ALL_HWS = os.getenv("WITH_ALL_HWS", "0") == "1"


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


def build_all_binaries(build_cosig, build_wt):
    logging.info(
        f"Building coordinatord at '{COORDINATORD_VERSION}' in '{COORDINATORD_SRC_DIR}'"
    )
    build_src(
        COORDINATORD_SRC_DIR,
        COORDINATORD_VERSION,
        "https://github.com/revault/coordinatord",
    )

    if build_cosig:
        logging.info(
            f"Building cosignerd at '{COSIGNERD_VERSION}' in '{COSIGNERD_SRC_DIR}'"
        )
        build_src(
            COSIGNERD_SRC_DIR, COSIGNERD_VERSION, "https://github.com/revault/cosignerd"
        )

    if build_wt:
        logging.info(
            f"Building miradord at '{MIRADORD_VERSION}' in '{MIRADORD_SRC_DIR}'"
        )
        build_src(
            MIRADORD_SRC_DIR, MIRADORD_VERSION, "https://github.com/revault/miradord"
        )

    logging.info(f"Building revaultd at '{REVAULTD_VERSION}' in '{REVAULTD_SRC_DIR}'")
    build_src(REVAULTD_SRC_DIR, REVAULTD_VERSION, "https://github.com/revault/revaultd")

    if WITH_GUI:
        logging.info(
            f"Building revault-gui at '{REVAULT_GUI_VERSION}' in '{REVAULT_GUI_SRC_DIR}',"
            " this may take some time"
        )
        build_src(
            REVAULT_GUI_SRC_DIR,
            REVAULT_GUI_VERSION,
            "https://github.com/edouardparis/revault-gui",
        )

        logging.info("Building revault-gui's dummysigner")
        subprocess.check_call(
            [
                "cargo",
                "build",
                "--manifest-path",
                f"{REVAULT_GUI_SRC_DIR}/contrib/tools/dummysigner/Cargo.toml",
            ]
        )


def bitcoind():
    bitcoind = BitcoinD(bitcoin_dir=bitcoind_dir())
    bitcoind.startup()

    bitcoind.rpc.createwallet(bitcoind.rpc.wallet_name, False, False, "", False, True)

    while bitcoind.rpc.getbalance() < 50:
        bitcoind.rpc.generatetoaddress(1, bitcoind.rpc.getnewaddress())

    while bitcoind.rpc.getblockcount() <= 1:
        time.sleep(0.1)

    return bitcoind


def deploy(
    n_stks, n_mans, n_stkmans, csv, mans_thresh=None, with_cosigs=False, policies=[]
):
    with_wts = len(policies) > 0

    if not POSTGRES_IS_SETUP:
        logging.error("I need the Postgres environment variable to be set.")
        print("Example:")
        print(f'  POSTGRES_USER="revault" POSTGRES_PASS="revault" {sys.argv[0]}')
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

    if n_stks + n_stkmans < 1:
        logging.error("Need at least 1 stakeholder")
        sys.exit(1)
    if n_mans + n_stkmans < 1:
        logging.error("Need at least 1 manager")
        sys.exit(1)
    if mans_thresh is not None and (
        mans_thresh > n_mans + n_stkmans or mans_thresh < 1
    ):
        logging.error("Invalid managers threshold")
        sys.exit(1)

    for p in policies:
        if not os.path.isfile(p):
            logging.error(f"No plugin at '{p}'")
            sys.exit(1)

    if os.path.isdir(BASE_DIR):
        logging.warning("Base directory exists already")
        resp = input(f"Remove non-empty '{BASE_DIR}' and start fresh? (y/n) ")
        if resp.lower() == "y":
            shutil.rmtree(BASE_DIR)
        else:
            logging.info("Exiting")
            sys.exit(1)

    logging.info("Checking the source directories..")
    build_all_binaries(build_cosig=with_cosigs, build_wt=with_wts)

    logging.info("Setting up bitcoind")
    bd = bitcoind()

    # In any case cleanup bitcoind before exiting
    try:
        logging.info(
            f"Deploying a Revault network with {n_stks} only-stakeholders,"
            f" {n_mans} only-managers, {n_stkmans} both stakeholders and managers,"
            f" a CSV of {csv} and a managers threshold of {mans_thresh or n_mans + n_stkmans}"
        )
        # Monkey patch the servers binaries paths
        test_framework.revaultd.REVAULTD_PATH = os.path.join(
            REVAULTD_SRC_DIR, "target", "debug", "revaultd"
        )
        test_framework.coordinatord.COORDINATORD_PATH = os.path.join(
            COORDINATORD_SRC_DIR, "target", "debug", "coordinatord"
        )
        test_framework.cosignerd.COSIGNERD_PATH = os.path.join(
            COSIGNERD_SRC_DIR, "target", "debug", "cosignerd"
        )
        test_framework.miradord.MIRADORD_PATH = os.path.join(
            MIRADORD_SRC_DIR, "target", "debug", "miradord"
        )
        rn = RevaultNetwork(
            BASE_DIR,
            bd,
            executor(),
            POSTGRES_USER,
            POSTGRES_PASS,
            POSTGRES_HOST,
        )
        rn.deploy(
            n_stks,
            n_mans,
            n_stkmans,
            csv,
            mans_thresh,
            with_watchtowers=with_wts,
            with_cosigs=with_cosigs,
        )

        if with_wts:
            # NOTE: no config. We use hardcoded values for the demo.
            policies = [{"path": p} for p in policies]
            for stk in rn.stk_wallets + rn.stkman_wallets:
                stk.watchtower.add_plugins(policies)

        dummysigner_conf_file = os.path.join(BASE_DIR, "dummysigner.toml")
        # We use a hack to avoid having to modify the test_framework to include the GUI.
        if WITH_GUI:
            emergency_address = rn.emergency_address
            deposit_desc = rn.deposit_desc
            unvault_desc = rn.unvault_desc
            cpfp_desc = rn.cpfp_desc
            with open(dummysigner_conf_file, "w") as f:
                f.write(f'emergency_address = "{emergency_address}"\n')
                for i, stk in enumerate(rn.stk_wallets):
                    f.write("[[keys]]\n")
                    f.write(f'name = "stakeholder_{i}_key"\n')
                    f.write(f'xpriv = "{stk.stk_keychain.hd.get_xpriv()}"\n')
                for i, man in enumerate(rn.man_wallets):
                    f.write("[[keys]]\n")
                    f.write(f'name = "manager_{i}_key"\n')
                    f.write(f'xpriv = "{man.man_keychain.hd.get_xpriv()}"\n')
                for i, stkman in enumerate(rn.stkman_wallets):
                    f.write("[[keys]]\n")
                    f.write(f'name = "stkman_{i}_stakeholder_key"\n')
                    f.write(f'xpriv = "{stkman.stk_keychain.hd.get_xpriv()}"\n')
                    f.write("[[keys]]\n")
                    f.write(f'name = "stkman_{i}_manager_key"\n')
                    f.write(f'xpriv = "{stkman.man_keychain.hd.get_xpriv()}"\n')
                f.write("[descriptors]\n")
                f.write(f'deposit_descriptor = "{deposit_desc}"\n')
                f.write(f'unvault_descriptor = "{unvault_desc}"\n')
                f.write(f'cpfp_descriptor = "{cpfp_desc}"\n')

            for p in rn.participants():
                p.gui_conf_file = os.path.join(
                    p.datadir_with_network, "gui_config.toml"
                )
                with open(p.gui_conf_file, "w") as f:
                    f.write(f"revaultd_config_path = '{p.conf_file}'\n")
                    f.write(f"revaultd_path = '{REVAULTD_PATH}'\n")
                    f.write(f"log_level = '{LOG_LEVEL}'\n")
                    f.write(f"debug = {'true' if DEBUG_GUI else 'false'}")
            revault_gui = os.path.join(
                REVAULT_GUI_SRC_DIR, "target", "debug", "revault-gui"
            )
            dummysigner = os.path.join(
                REVAULT_GUI_SRC_DIR,
                "contrib",
                "tools",
                "dummysigner",
                "target",
                "debug",
                "dummysigner",
            )

        revault_cli = os.path.join(REVAULTD_SRC_DIR, "target", "debug", "revault-cli")
        aliases_file = os.path.join(BASE_DIR, "aliases.sh")
        with open(aliases_file, "w") as f:
            f.write('PS1="(Revault demo) $PS1"\n')  # It's a hack it shouldn't be there
            f.write(f"alias bd=\"bitcoind -datadir='{bd.bitcoin_dir}'\"\n")
            f.write(
                f"alias bcli=\"bitcoin-cli -datadir='{bd.bitcoin_dir}' -rpcwallet='{bd.rpc.wallet_name}'\"\n"
            )
            for i, stk in enumerate(rn.stk_wallets):
                f.write(f'alias stk{i}cli="{revault_cli} --conf {stk.conf_file}"\n')
                f.write(f'alias stk{i}d="{REVAULTD_PATH} --conf {stk.conf_file}"\n')
                if WITH_GUI:
                    f.write(
                        f"alias stk{i}gui='{revault_gui} --conf {stk.gui_conf_file}'\n"
                    )
                    if WITH_ALL_HWS:
                        f.write(
                            f"alias stk{i}hw='{dummysigner} {stk.stk_keychain.hd.get_xpriv()}'\n"
                        )
            for i, man in enumerate(rn.man_wallets):
                f.write(f'alias man{i}cli="{revault_cli} --conf {man.conf_file}"\n')
                f.write(f'alias man{i}d="{REVAULTD_PATH} --conf {man.conf_file}"\n')
                if WITH_GUI:
                    f.write(
                        f"alias man{i}gui='{revault_gui} --conf {man.gui_conf_file}'\n"
                    )
                    if WITH_ALL_HWS:
                        f.write(
                            f"alias man{i}hw='{dummysigner} {man.man_keychain.hd.get_xpriv()}'\n"
                        )
            for i, stkman in enumerate(rn.stkman_wallets):
                f.write(
                    f'alias stkman{i}cli="{revault_cli} --conf {stkman.conf_file}"\n'
                )
                f.write(
                    f'alias stkman{i}d="{REVAULTD_PATH} --conf {stkman.conf_file}"\n'
                )
                if WITH_GUI:
                    f.write(
                        f"alias stkman{i}gui='{revault_gui} --conf {stkman.gui_conf_file}'\n"
                    )
                    if WITH_ALL_HWS:
                        f.write(
                            f"alias stkman{i}hwstk='{dummysigner} {stkman.stk_keychain.hd.get_xpriv()}'\n"
                        )
                        f.write(
                            f"alias stkman{i}hwman='{dummysigner} {stkman.man_keychain.hd.get_xpriv()}'\n"
                        )
            # hw for all the keys.
            if WITH_GUI:
                f.write(f"alias hw='{dummysigner} --conf {dummysigner_conf_file}'\n")

        with open(aliases_file, "r") as f:
            available_aliases = "".join(f.readlines()[1:])
        print("Dropping you into a shell. Exit to end the session.", end="\n\n")
        print(f"Available aliases: \n{available_aliases}\n")
        # In any case clean up all daemons before exiting
        try:
            subprocess.call([SHELL, "--init-file", f"{aliases_file}", "-i"])
        except Exception as e:
            logging.error(f"Got error: '{str(e)}'")
            logging.error(traceback.format_exc())
        finally:
            logging.info("Cleaning up Revault deployment")
            rn.cleanup()
    except Exception as e:
        logging.error(f"Got error: '{str(e)}'")
        logging.error(traceback.format_exc())
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


def parse_args():
    parser = argparse.ArgumentParser()
    deploy_config = parser.add_argument_group("Deployment configuration")
    deploy_config.add_argument(
        "-stks",
        "--stakeholders",
        type=int,
        help="The number of only-stakeholder",
        required=True,
    )
    deploy_config.add_argument(
        "-mans",
        "--managers",
        type=int,
        help="The number of only-manager",
        required=True,
    )
    deploy_config.add_argument(
        "-stkmans",
        "--stakeholder-managers",
        type=int,
        help="The number of both stakeholder-manager",
        required=True,
    )
    deploy_config.add_argument(
        "-csv",
        "--timelock",
        type=int,
        help="The number of blocks during which an Unvault attempt can be canceled",
        required=True,
    )
    deploy_config.add_argument(
        "-mansthresh",
        "--managers-threshold",
        type=int,
    )
    deploy_config.add_argument(
        "-cosigs",
        "--with-cosigning-servers",
        action="store_true",
        help="Enable cosigning servers to allow Spend policies at the cost of weaker assumptions",
    )
    deploy_config.add_argument(
        "-policy",
        "--spending-policy",
        action="append",
        default=[],
        dest="policies",
        help="Enforce a spending policy on all watchtowers by specifying a path to a watchtower plugin",
    )
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()

    args = parse_args()
    deploy(
        args.stakeholders,
        args.managers,
        args.stakeholder_managers,
        args.timelock,
        args.managers_threshold,
        args.with_cosigning_servers,
        args.policies,
    )
