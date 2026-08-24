#!/usr/bin/env bash
# Installs the caps-latch evdev daemon. Run with sudo.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer needs root: sudo $0" >&2
    exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! python3 -c "import evdev" 2>/dev/null; then
    echo "python3-evdev is not installed. Install it first:" >&2
    echo "    sudo apt install python3-evdev" >&2
    exit 1
fi

modprobe uinput 2>/dev/null || true
echo uinput > /etc/modules-load.d/caps-latch.conf

install -Dm755 "$SRC/caps-latch.py"      /usr/local/bin/caps-latch
install -Dm644 "$SRC/caps-latch.service" /etc/systemd/system/caps-latch.service

if [ ! -e /etc/caps-latch.conf ]; then
    install -Dm644 "$SRC/caps-latch.conf" /etc/caps-latch.conf
else
    echo "Keeping existing /etc/caps-latch.conf"
fi

systemctl daemon-reload
systemctl enable --now caps-latch
echo
systemctl --no-pager --full status caps-latch | head -20
