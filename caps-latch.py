#!/usr/bin/env python3
"""caps-latch — require Caps Lock to be held before it switches on.

Runs below the compositor, at the evdev layer. The physical keyboards are
grabbed exclusively (EVIOCGRAB) and every event is mirrored to a single
virtual keyboard, untouched, with one exception: Caps Lock.

  Caps Lock currently OFF -> the press is withheld. Release it before the
      configured delay and nothing is ever emitted, so the OS never toggles
      the lock and the LED never flickers. Keep holding past the delay and
      the real press is emitted while the key is still down.

  Caps Lock currently ON  -> the press is forwarded immediately. Switching
      it back off is never delayed.

Direction is decided by querying LED_CAPSL on our own virtual device, which
is what the compositor updates, so it stays correct even when something
else toggles the lock (an on-screen keyboard, another session, xdotool).
Internal tracking is used only if that query is unavailable.

Killing the daemon closes the grab fds, which releases the keyboards back
to the system, so a crash degrades to plain Caps Lock rather than no input.
"""

import errno
import os
import selectors
import signal
import sys
import time

import evdev
from evdev import InputDevice, UInput, ecodes

CONFIG_PATH = "/etc/caps-latch.conf"
VIRTUAL_NAME = "caps-latch virtual keyboard"
DEFAULT_DELAY_MS = 1000
RESCAN_INTERVAL = 2.0
# Standard keyboard key range, always advertised on the virtual device so a
# keyboard hotplugged after startup can still pass every ordinary key.
BASE_KEYS = range(1, 128)


def log(msg):
    print(f"[caps-latch] {msg}", flush=True)


def read_delay_ms(path=CONFIG_PATH):
    """Parse `delay_ms = N` out of the config file. Missing file is fine."""
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return DEFAULT_DELAY_MS
    except OSError as exc:
        log(f"could not read {path} ({exc}); using default delay")
        return DEFAULT_DELAY_MS

    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "delay_ms":
            continue
        try:
            parsed = int(value.strip())
        except ValueError:
            log(f"bad delay_ms value {value.strip()!r}; using default")
            return DEFAULT_DELAY_MS
        if parsed < 0:
            log(f"negative delay_ms {parsed}; using default")
            return DEFAULT_DELAY_MS
        return parsed
    return DEFAULT_DELAY_MS


def is_target_keyboard(dev):
    """A real typing keyboard: has Caps Lock and letter keys."""
    keys = dev.capabilities().get(ecodes.EV_KEY, [])
    return ecodes.KEY_CAPSLOCK in keys and ecodes.KEY_A in keys


class CapsLockDelay:
    def __init__(self, delay_ms):
        self.delay = delay_ms / 1000.0
        self.selector = selectors.DefaultSelector()
        self.sources = {}          # path -> InputDevice (grabbed)
        self.ui = None
        self.caps_on = False       # fallback state if LED query is unusable
        self.led_query_ok = True
        self.held_since = None     # monotonic time of a withheld Caps press
        self.committed = False     # we forwarded the press, so forward the release
        self.running = True

    # ---- device management -------------------------------------------------

    def _candidates(self):
        found = []
        for path in evdev.list_devices():
            try:
                dev = InputDevice(path)
            except OSError:
                continue
            virtual_path = self.ui.device.path if self.ui and self.ui.device else None
            if dev.name == VIRTUAL_NAME or path == virtual_path:
                dev.close()
                continue
            if not is_target_keyboard(dev):
                dev.close()
                continue
            found.append(dev)
        return found

    def _build_capabilities(self, devs):
        keys = set(BASE_KEYS)
        misc = set()
        for dev in devs:
            caps = dev.capabilities()
            keys.update(caps.get(ecodes.EV_KEY, []))
            misc.update(caps.get(ecodes.EV_MSC, []))
        keys.add(ecodes.KEY_CAPSLOCK)
        # EV_REP is deliberately omitted: the source devices already emit
        # repeat events (value 2) that we forward, and advertising EV_REP here
        # would make the kernel generate a second set.
        caps = {
            ecodes.EV_KEY: sorted(keys),
            ecodes.EV_LED: [ecodes.LED_NUML, ecodes.LED_CAPSL, ecodes.LED_SCROLLL],
        }
        if misc:
            caps[ecodes.EV_MSC] = sorted(misc)
        return caps

    def _grab(self, dev):
        try:
            dev.grab()
        except OSError as exc:
            log(f"could not grab {dev.path} ({dev.name}): {exc}")
            dev.close()
            return False
        self.sources[dev.path] = dev
        self.selector.register(dev, selectors.EVENT_READ, dev)
        log(f"grabbed {dev.path} ({dev.name})")
        return True

    def _drop(self, dev):
        self.sources.pop(dev.path, None)
        try:
            self.selector.unregister(dev)
        except (KeyError, ValueError):
            pass
        try:
            dev.ungrab()
        except OSError:
            pass
        try:
            dev.close()
        except OSError:
            pass
        log(f"released {dev.path}")

    def rescan(self):
        for dev in self._candidates():
            if dev.path in self.sources:
                dev.close()
                continue
            self._grab(dev)

    # ---- caps lock state ---------------------------------------------------

    def caps_is_on(self):
        if self.led_query_ok and self.ui.device is not None:
            try:
                return ecodes.LED_CAPSL in self.ui.device.leds()
            except OSError as exc:
                log(f"LED query unavailable ({exc}); falling back to internal state")
                self.led_query_ok = False
        return self.caps_on

    def emit_caps(self, value):
        self.ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, value)
        self.ui.syn()
        if value == 1:
            self.caps_on = not self.caps_on

    # ---- event handling ----------------------------------------------------

    def handle_caps(self, value):
        if value == 1:                      # press
            if self.caps_is_on():
                self.committed = True       # instant off
                self.held_since = None
                self.emit_caps(1)
            else:
                self.committed = False
                self.held_since = time.monotonic()
        elif value == 2:                    # autorepeat
            if self.committed:
                self.emit_caps(2)
        else:                               # release
            if self.committed:
                self.emit_caps(0)
            self.committed = False
            self.held_since = None

    def check_hold(self):
        if self.held_since is None or self.committed:
            return
        if time.monotonic() - self.held_since >= self.delay:
            self.held_since = None
            self.committed = True
            self.emit_caps(1)

    def pump(self, dev):
        try:
            events = list(dev.read())
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno in (errno.ENODEV, errno.EBADF):
                self._drop(dev)
                return
            raise

        for event in events:
            if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_CAPSLOCK:
                self.handle_caps(event.value)
                continue
            if event.type == ecodes.EV_SYN:
                self.ui.syn()
                continue
            self.ui.write(event.type, event.code, event.value)

    def drain_virtual(self):
        """Consume LED updates the compositor writes back to our device."""
        try:
            for event in self.ui.device.read():
                if event.type == ecodes.EV_LED and event.code == ecodes.LED_CAPSL:
                    self.caps_on = bool(event.value)
        except BlockingIOError:
            pass
        except OSError:
            pass

    # ---- lifecycle ---------------------------------------------------------

    def stop(self, *_):
        self.running = False

    def run(self):
        devs = self._candidates()
        if not devs:
            log("no keyboards with Caps Lock found; nothing to do")
            return 1

        capabilities = self._build_capabilities(devs)
        try:
            self.ui = UInput(capabilities, name=VIRTUAL_NAME, version=1)
        except OSError as exc:
            for dev in devs:
                dev.close()
            log(f"could not create virtual keyboard: {exc}")
            log("is the uinput module loaded, and are we running as root?")
            return 1
        if self.ui.device is None:
            # Without a readable node for the virtual device we cannot ask the
            # compositor what the lock state is; fall back to tracking it.
            self.led_query_ok = False
            log("virtual keyboard created, but its device node could not be "
                "resolved; using internal caps-state tracking")
        else:
            log(f"virtual keyboard at {self.ui.device.path}")

        # Give the compositor a moment to notice the virtual keyboard before
        # the real ones disappear, so there is no window with no keyboard.
        time.sleep(0.3)

        for dev in devs:
            self._grab(dev)
        if not self.sources:
            log("could not grab any keyboard; exiting without taking input")
            self.ui.close()
            return 1

        if self.ui.device is not None:
            self.selector.register(self.ui.device, selectors.EVENT_READ, self.ui.device)
        self.caps_on = self.caps_is_on()
        log(f"running; delay {self.delay * 1000:.0f} ms, caps currently "
            f"{'on' if self.caps_on else 'off'}")

        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        next_scan = time.monotonic() + RESCAN_INTERVAL
        while self.running:
            # Wake early enough to fire a pending hold on time.
            timeout = 0.05 if self.held_since is not None else 0.5
            for key, _ in self.selector.select(timeout):
                if key.data is self.ui.device:
                    self.drain_virtual()
                else:
                    self.pump(key.data)
            self.check_hold()

            now = time.monotonic()
            if now >= next_scan:
                next_scan = now + RESCAN_INTERVAL
                self.rescan()
                if not self.sources:
                    log("all keyboards disappeared; exiting")
                    break

        self.shutdown()
        return 0

    def shutdown(self):
        log("shutting down, releasing keyboards")
        for dev in list(self.sources.values()):
            self._drop(dev)
        if self.ui is not None:
            try:
                self.ui.close()
            except OSError:
                pass


def main():
    if os.geteuid() != 0:
        log("must run as root (needs EVIOCGRAB on /dev/input and /dev/uinput)")
        return 1
    delay_ms = read_delay_ms()
    return CapsLockDelay(delay_ms).run()


if __name__ == "__main__":
    sys.exit(main())
