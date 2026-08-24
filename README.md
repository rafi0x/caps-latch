# caps-latch

You hit Caps Lock without meaning to. It happens all the time.
Your pinky slides, you keep typing, and a few seconds later you look up
and the screen is FULL OF THIS. So you delete it and type it again.

That's the whole problem. Caps Lock sits right where your fingers are,
you almost never need it, and it ruins a sentence every time you brush it.

#### Now it waits a second before doing anything. If you meant it, hold it. If you didn't, you won't even notice it's there.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/rafi0x/caps-latch/master/install.sh | sudo bash
```

That's it, it's already running. It grabs what it needs and sets up the
service for you.

Rather do it by hand:

```bash
git clone https://github.com/rafi0x/caps-latch
cd caps-latch
sudo ./install.sh
```

## Change the delay

```bash
sudo nano /etc/caps-latch.conf
```

```ini
delay_ms = 1000   # 0 turns this off and gives you normal Caps Lock back
```

Then:

```bash
sudo systemctl restart caps-latch
```

## What it does

| You do                   | What happens                             |
| ------------------------ | ---------------------------------------- |
| Tap it while Caps is off | Nothing. No toggle, no light             |
| Hold it for a second     | Caps turns on while you're still holding |
| Tap it while Caps is on  | Turns off right away                     |
| Press any other key      | Nothing changes                          |

## How it works

A small daemon reads your keyboards directly and passes everything through
a fake keyboard it creates. Caps Lock presses get held back until the timer
runs out. Stop the daemon and your keyboards go back to normal.

You need Linux with `uinput`, `python3-evdev`, systemd, and root.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/rafi0x/caps-latch/master/uninstall.sh | sudo bash
```

## License

MIT — see [LICENSE](LICENSE).

