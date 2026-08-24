#!/usr/bin/env bash
# Removes the caps-latch daemon. Run with sudo.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "This uninstaller needs root: sudo $0" >&2
    exit 1
fi

systemctl disable --now caps-latch 2>/dev/null || true
rm -f /etc/systemd/system/caps-latch.service
rm -f /usr/local/bin/caps-latch
rm -f /etc/modules-load.d/caps-latch.conf
systemctl daemon-reload

if [ -e /etc/caps-latch.conf ]; then
    echo "Left /etc/caps-latch.conf in place; remove it by hand if you want it gone."
fi

echo "Removed. Your keyboards are no longer grabbed."
