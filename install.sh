#!/usr/bin/env bash
# Installs the caps-latch evdev daemon. Run with sudo.

set -euo pipefail

REPO="${CAPS_LATCH_REPO:-rafi0x/caps-latch}"
REF="${CAPS_LATCH_REF:-master}"
RAW="${CAPS_LATCH_RAW:-https://raw.githubusercontent.com/$REPO/$REF}"
FILES=(caps-latch.py caps-latch.service caps-latch.conf)

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer needs root. Try:" >&2
    echo "    curl -fsSL $RAW/install.sh | sudo bash" >&2
    exit 1
fi

SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]:-}" ]; then
    maybe="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [ -f "$maybe/caps-latch.py" ] && SRC="$maybe"
fi

if [ -z "$SRC" ]; then
    command -v curl >/dev/null || { echo "curl is required to download caps-latch." >&2; exit 1; }
    SRC="$(mktemp -d)"
    trap 'rm -rf "$SRC"' EXIT
    echo "Fetching caps-latch ($REPO@$REF)..."
    for f in "${FILES[@]}"; do
        curl -fsSL "$RAW/$f" -o "$SRC/$f" ||
            { echo "Could not download $f from $RAW" >&2; exit 1; }
    done
    # A truncated or 404-as-200 download would install a broken daemon.
    head -1 "$SRC/caps-latch.py" | grep -q python ||
        { echo "Downloaded caps-latch.py does not look right." >&2; exit 1; }
fi

# python3-evdev is the one real dependency; install it if we know how.
if ! python3 -c "import evdev" 2>/dev/null; then
    echo "Installing python3-evdev..."
    if   command -v apt-get >/dev/null; then apt-get update -qq && apt-get install -y python3-evdev
    elif command -v dnf     >/dev/null; then dnf install -y python3-evdev
    elif command -v pacman  >/dev/null; then pacman -Sy --noconfirm python-evdev
    elif command -v zypper  >/dev/null; then zypper --non-interactive install python3-evdev
    elif command -v apk     >/dev/null; then apk add --no-cache py3-evdev
    else
        echo "Could not work out your package manager." >&2
        echo "Install the python3 evdev module yourself, then run this again." >&2
        exit 1
    fi
    python3 -c "import evdev" 2>/dev/null ||
        { echo "python3-evdev still is not importable. Install it by hand." >&2; exit 1; }
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
