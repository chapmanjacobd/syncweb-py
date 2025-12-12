#!/bin/sh

tmp=$(mktemp -d)
exe=$(python -P -c 'import os; from syncweb.consts import SCRIPT_DIR; print(os.path.join(SCRIPT_DIR,"syncthing"))')
$exe generate --home $tmp
mv "$tmp/config.xml" tests/config.xml
