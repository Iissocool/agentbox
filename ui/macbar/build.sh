#!/usr/bin/env bash
# Build AgentboxMenuBar.app — macOS menu bar application
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/AgentboxMenuBar/AgentboxMenuBarApp.swift"
DIST="$ROOT/dist"
APP="$DIST/AgentboxMenuBar.app"
BIN="$APP/Contents/MacOS/AgentboxMenuBar"

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
