#!/bin/bash
# Removes the de-identification watcher LaunchAgent installed by
# install_watcher_launchagent.sh.
#
# Run this once, from Terminal:
#     chmod +x uninstall_watcher_launchagent.sh
#     ./uninstall_watcher_launchagent.sh

set -euo pipefail

LABEL="com.labdeidentifier.watcher"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Removed LaunchAgent: $LABEL"
else
    echo "No LaunchAgent found at $PLIST_PATH -- nothing to remove."
fi
