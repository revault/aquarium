# Aquarium 🧙 🐟

A Revault sandbox

## About

Being a complete custody solution, configuring all the parts of a Revault deployment is a bit
tedious. Aquarium is a Python script re-using the [`revaultd`](https://github.com/revault/revaultd)
functional testing framework to provide a turnkey solution to deploy a Revault setup on a regtest
network.

The [`aquarium.py`](aquarium.py) script will fetch the source of the different Revault binaries 
(`revaultd`, `revault-gui`, `coordinatord`, `cosignerd`) at a given version, compile them using
[`Cargo`](https://doc.rust-lang.org/cargo/), start a (single) `bitcoind` in `regtest` mode, hook
into the [`test_framework`](`test_framework/`) to write all the configuration (Bitcoin keys,
communication keys, script descriptors, connections, ..) and finally drop you in a shell with
pre-defined `alias`es.

The aquarium only runs on Unix system for now.

## Usage

### Dependencies

First of all, the testing framework has a few dependencies (for key generation, DB connection and
bitcoind RPC specifically). The recommended method for installing them is by using a [`venv`](https://docs.python.org/3/library/venv.html).
```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

Also, you will need to install [`Cargo`](https://doc.rust-lang.org/cargo/getting-started/installation.html)
which you very likely already have installed if you have a Rust toolchain.

You will need a version of at least `1.43` for building `revaultd`, `coordinatord` and `cosignerd`.
If you are going to use the GUI, the latest stable version is required to build `revault-gui`. You
can check your version with:
```
cargo --version
```

### Running

Clone the `aquarium` repo first:
```
git clone https://github.com/revault/aquarium
cd aquarium
```

The testing framework will spin up the Coordinator, which needs access to a Postgre backend. The
easiest way to set one up is by using [Docker](https://docs.docker.com/engine/install/):
```
docker run --rm -d -p 5432:5432 --name postgres-coordinatord -e POSTGRES_PASSWORD=revault -e POSTGRES_USER=revault -e POSTGRES_DB=coordinator_db postgres:alpine
```
If you already have a Postgre backend set up, the script will just need credentials (and optionally
a `POSTGRES_HOST`) and will take care of creating the database (and removing it at teardown).

To deploy Revault you'll need to specify the number of Stakeholders (participants not taking
actively part in spendings but pre-signing authorizations of spending), Managers (participants
taking part in spending using the pre-signed transactions) and Stakeholders-Managers (participants
acting as both), and the Unvault timelock duration (number of blocks during which any participant
or watchtower can Cancel a spending attempt). Optionally, you can also set a threshold for the
managers (eg `2` out of the `3` managers are enough to Spend a pre-signed Unvault):
```
$ ./aquarium.py --help
usage: aquarium.py [-h] -stks STAKEHOLDERS -mans MANAGERS -stkmans STAKEHOLDER_MANAGERS -csv TIMELOCK [-mansthresh MANAGERS_THRESHOLD]

optional arguments:
  -h, --help            show this help message and exit

Deployment configuration:
  -stks STAKEHOLDERS, --stakeholders STAKEHOLDERS
                        The number of only-stakeholder
  -mans MANAGERS, --managers MANAGERS
                        The number of only-manager
  -stkmans STAKEHOLDER_MANAGERS, --stakeholder-managers STAKEHOLDER_MANAGERS
                        The number of both stakeholder-manager
  -csv TIMELOCK, --timelock TIMELOCK
                        The number of blocks during which an Unvault attempt can be canceled
  -mansthresh MANAGERS_THRESHOLD, --managers-threshold MANAGERS_THRESHOLD
```

Assuming you've set a PostgreSQL backend with credentials `revault:revault` as with the Docker
example above, and you want to deploy a Revault setup with 1 Stakeholder, 1 Manager and 2
Stakeholder-Managers who can Spend with a threshold of `2` after `6` blocks:
```
POSTGRES_USER=revault POSTGRES_PASS=revault ./aquarium.py --stakeholders 1 --managers 1 --stakeholder-managers 2 --timelock 6 --managers-threshold 2
```

You will get into a shell where you can use the `alias`es to start messing around:
```
Dropping you into a shell. Exit to end the session.

Available aliases: 
alias bd="bitcoind -datadir='/home/darosior/projects/revault/aquarium/demo/bitcoind'"
alias bcli="bitcoin-cli -datadir='/home/darosior/projects/revault/aquarium/demo/bitcoind' -rpcwallet='revaultd-tests'"
alias stk0cli="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revault-cli --conf /home/darosior/projects/revault/aquarium/demo/revaultd-stk-0/config.toml"
alias stk0d="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revaultd --conf /home/darosior/projects/revault/aquarium/demo/revaultd-stk-0/config.toml"
alias man0cli="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revault-cli --conf /home/darosior/projects/revault/aquarium/demo/revaultd-man-0/config.toml"
alias man0d="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revaultd --conf /home/darosior/projects/revault/aquarium/demo/revaultd-man-0/config.toml"
alias stkman0cli="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revault-cli --conf /home/darosior/projects/revault/aquarium/demo/revaultd-man-0/config.toml"
alias stkman0d="/home/darosior/projects/revault/aquarium/src/revaultd/target/debug/revaultd --conf /home/darosior/projects/revault/aquarium/demo/revaultd-man-0/config.toml"


(Revault demo) darosior@darosior:~/projects/revault/aquarium$ stkman1cli getdepositaddress
{
  "result": {
    "address": "bcrt1qmelp89d78y5ujrthqu6sdtc39kraadw3lap8skfzd24jcjt9k8qq4n8lxj"
  }
}
(Revault demo) darosior@darosior:~/projects/revault/aquarium$ bcli sendtoaddress bcrt1qmelp89d78y5ujrthqu6sdtc39kraadw3lap8skfzd24jcjt9k8qq4n8lxj 0.42
aa1222b51c2d0bacbcec65938650165a678ce5cfede5743ae85b66d1c2787695
(Revault demo) darosior@darosior:~/projects/revault/aquarium$ stkman1cli listvaults
{
  "result": {
    "vaults": [
      {
        "address": "bcrt1qmelp89d78y5ujrthqu6sdtc39kraadw3lap8skfzd24jcjt9k8qq4n8lxj",
        "amount": 42000000,
        "blockheight": 0,
        "derivation_index": 0,
        "received_at": 1628591587,
        "status": "unconfirmed",
        "txid": "aa1222b51c2d0bacbcec65938650165a678ce5cfede5743ae85b66d1c2787695",
        "updated_at": 1628591587,
        "vout": 1
      }
    ]
  }
}
(Revault demo) darosior@darosior:~/projects/revault/aquarium$ bcli generatetoaddress 7 $(bcli getnewaddress) 
[
  "0550e0a3e06c220964fcf84eb9bbec03480762adae698749d54020897dc2bd81",
  "4aec1f8347bd5147d9afc3939dfd5ddd3f0de9190da918aed582d511f6b561e1",
  "61baff64f27c049cb5dac2ff9149ac9f09f8a92f373b12c6e4bac02a5dba51fa",
  "67d19b98389e4553321cb2254f1cf1153bd51a6db93ca878f4344bc46ca6eaad",
  "097b833b445e1714d158e85c0ff0fab1a4295fd9705a9997ea1b401183718b84",
  "1f7cf43bf899647b80daaa4668fe10d7c22dbda2ab1b00b183ee88ff200b623a",
  "5a5b55b43a56e3b76ff071deba559421c6e1c169c951cb47e13f1c168bf44caa"
]
(Revault demo) darosior@darosior:~/projects/revault/aquarium$ stkman1cli listvaults
{
  "result": {
    "vaults": [
      {
        "address": "bcrt1qmelp89d78y5ujrthqu6sdtc39kraadw3lap8skfzd24jcjt9k8qq4n8lxj",
        "amount": 42000000,
        "blockheight": 102,
        "derivation_index": 0,
        "received_at": 1628591587,
        "status": "funded",
        "txid": "aa1222b51c2d0bacbcec65938650165a678ce5cfede5743ae85b66d1c2787695",
        "updated_at": 1628591631,
        "vout": 1
      }
    ]
  }
}
```

To start using the GUI version of one of the participants:
```
stk0gui >/dev/null &
```
(redirecting `stdout` here to avoid getting annoyed by the logs)

The above example will start the GUI of the first stakeholder. You can then create a vault out of
a deposit (which you can create using `bcli` as shown just before). In order to create a vault you
will have to sign the revocation transactions: for testing purposes `revault-gui` provides a dummy
signer imitating the flow of signing the transactions on a hardware wallet. Mind to start the dummy
signer corresponding to the participant, for instance here it would be:
```
stk0hw &
```

You'll just have to click 'sign' on the GUI side and then 'confirm' on the signer side. Once every
stakeholder has signed the pre-signed transactions, the vault is created. It can then be delegated
(again requiring all stakeholders' signatures) and eventually spent by the managers (and may be
canceled..).

__Be careful to only start a single dummy signer at a time__, and the one of the right participant.
Otherwise the GUI will happily connect to whichever signer your provide it and you'll encounter an
error of the kind "cool you gave me a signature, but it's actually not for my participant".

### Tweaking

You can disable the GUI by setting the `WITH_GUI` environment variable to `0`.

The shell you are being dropped in is set to `bash` by default. This can be modified using the
`SHELL` environment variable, however this has only been tested with `bash`. In fact, it would most
likely break at the moment with another shell as we are using `--init-file` to provide `alias`es.

By default, all data directories are created in a `demo` parent directory created in the current
working directory. This can be changed using the `BASE_DIR` environment variable.

You can adjust the logging level using the `LOG_LEVEL` environment variable. This will affect the
daemons logs and test framework verbosity.

See [`aquarium.py`] for more environment variable. Notably, you can change the source code version
being fetched, and the directory in which repos are `git clone`d.

## Contributing

Contribution are very welcome, and especially for documentation that may be unclear to someone
external to the project or fixups to the `aquarium.py` script for environments we haven't tested in
ourselves!

For code modification, please keep in mind that we want to keep the divergence between this repo's
`test_framework` and `revaultd`'s one as low as possible to reduce the maintenance burden of
maintaining this repo up-to-date. If you have a fix for the `test_framework` itself, prefer proposing
it upstream to [`revaultd`](https://github.com/revault/revaultd).
