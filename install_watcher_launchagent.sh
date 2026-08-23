#!/bin/bash
# Installs the de-identification watcher as a macOS LaunchAgent that starts
# silently at login (no Terminal window, ever) and restarts automatically if
# the process ever stops.
#
# Run this once, from Terminal, inside this folder:
#     chmod +x install_watcher_launchagent.sh
#     ./install_watcher_launchagent.sh
#
# Re-running it is safe -- it replaces the existing LaunchAgent definition.

set -euo pipefail

LABEL="com.labdeidentifier.watcher"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER_SCRIPT="$SCRIPT_DIR/watch_and_deidentify.py"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

PYTHON3="$(command -v python3 || true)"
if [ -z "$PYTHON3" ]; then
    echo "Could not find 'python3' on PATH. Install Python 3 (python.org or 'brew install python') and re-run this script." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# Unload any existing copy first so re-running this script is always safe.
launchctl unload "$PLIST_PATH" 2>/dev/null || true

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON3</string>
        <string>$WATCHER_SCRIPT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/launchd_stderr.log</string>
</dict>
</plist>
PLIST

launchctl load -w "$PLIST_PATH"

echo "Installed LaunchAgent: $LABEL"
echo "It will start automatically every time you log in, and restart itself if it ever crashes."
echo ""
echo "It has also just been started right now. To check on it:"
echo "    launchctl list | grep $LABEL"
echo "    tail -f \"$SCRIPT_DIR/watcher.log\""
echo ""
echo "To stop it temporarily without uninstalling:"
echo "    launchctl unload \"$PLIST_PATH\""
echo "To start it again:"
echo "    launchctl load -w \"$PLIST_PATH\""
