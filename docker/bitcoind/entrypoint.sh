#!/usr/bin/env bash
set -e

# containers on linux share file permissions with hosts.
# assigning the same uid/gid from the host user
# ensures that the files can be read/write from both sides
if ! id bitcoin > /dev/null 2>&1; then
  USERID=${USERID:-1000}
  GROUPID=${GROUPID:-1000}

  echo "adding user bitcoin ($USERID:$GROUPID)"
  groupadd -f -g $GROUPID bitcoin
  useradd -r -u $USERID -g $GROUPID bitcoin
fi

exec bitcoind
