#!/usr/bin/env bash
# Build and launch AgentboxMenuBar.app — macOS menu bar application
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/AgentboxMenuBar/AgentboxMenuBarApp.swift"
DIST="$ROOT/dist"
APP="$DIST/AgentboxMenuBar.app"
BIN="$APP/Contents/MacOS/AgentboxMenuBar"
LOG="/tmp/agentbox_notch_drag.log"
AUTO_OPEN="${AGENTBOX_MACBAR_OPEN:-1}"

echo "Stopping existing AgentboxMenuBar process..."
pkill -f "$BIN" 2>/dev/null || pkill -x AgentboxMenuBar 2>/dev/null || true

for _ in {1..20}; do
    if ! pgrep -f "$BIN" >/dev/null 2>&1 && ! pgrep -x AgentboxMenuBar >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"

echo "Compiling Swift menu bar app..."
swiftc "$SRC" \
    -o "$BIN" \
    -parse-as-library \
    -O \
    -framework SwiftUI \
    -framework AppKit \
    -framework Combine

chmod +x "$BIN"

echo "Built: $APP"

if [[ "$AUTO_OPEN" != "0" ]]; then
    : > "$LOG"
    echo "Opening AgentboxMenuBar.app..."
    open -n "$APP"

    for _ in {1..40}; do
        if pgrep -f "$BIN" >/dev/null 2>&1 || pgrep -x AgentboxMenuBar >/dev/null 2>&1; then
            echo "Opened: $APP"
            echo "Drag/debug log: $LOG"
            exit 0
        fi
        sleep 0.25
    done

    echo "Warning: app was built but no AgentboxMenuBar process was detected after opening." >&2
    echo "Try manually: open \"$APP\"" >&2
    exit 1
fi
