# Jammy G — Bluetooth tool

This talks to the Jammy guitar over Bluetooth. It can turn the guitar's built-in
WiFi network on and read its name + password, so we can get onto it.

It writes NOTHING to the guitar's firmware. It only reads, and switches the WiFi
on — the same thing the old app did. No risk to the guitar.

You need: Linux with Bluetooth, and Nix. (You're on NixOS, so you're set.)

## Setup, one time only

```bash
git clone https://github.com/physarella/jammy-ble-tool.git
cd jammy-ble-tool
nix develop
```

If flakes complain, use:
```bash
nix --extra-experimental-features 'nix-command flakes' develop
```

Every time after that, just:
```bash
git pull
```
to grab the latest fixes before running anything.

## You do NOT need to pair this guitar (resolved 2026-09-08)

Skip pairing entirely — go straight to "Get the WiFi login" below.

We spent a while chasing Bluetooth pairing (button-hold + blue blink puts it
in pairing mode, etc) because commands were getting sent and nothing ever
came back. Turned out that had nothing to do with pairing: our messages were
missing a wrapper byte the real app always adds (confirmed by reading the
app's actual decompiled code), so the guitar never recognized them as valid
messages at all. Once that was fixed, everything worked on a plain,
unpaired connection — matching the real app, which never pairs either.

Confirmed separately: a phone's plain Bluetooth settings can't pair with
this guitar either. It just doesn't support standard pairing. Its own
`REGISTER` message (sent automatically by this tool) is its actual
security/login step, and that only needs a normal connection.

<details>
<summary>Old pairing instructions (kept for reference, not needed)</summary>

Turn the guitar on, press and hold the Volume knob for 5 seconds, watch for
the Power button blinking blue (that's pairing mode), then:

```bash
{
  echo "power on";                        sleep 1
  echo "agent on";                        sleep 1
  echo "default-agent";                   sleep 1
  echo "scan on";                         sleep 8
  echo "scan off";                        sleep 1
  echo "pair 8C:F7:10:7A:8B:43";          sleep 10
  echo "trust 8C:F7:10:7A:8B:43";         sleep 1
  echo "quit"
} | bluetoothctl
```

This never actually succeeded across several attempts (including from a
phone), which is what led to discovering it isn't needed at all.
</details>

## Get the WiFi login

```bash
python jammy_ble.py --address 8C:F7:10:7A:8B:43 wifi
```

This registers with the guitar, turns its WiFi on, and reads back the
network name + password. **By default it does not touch this machine's own
network at all** -- it just prints the credentials.

### Auto-join (only on a spare device, never one on a call/doing something else)

The guitar's hotspot only stays up ~15-20 seconds if nothing joins it --
too fast to alt-tab into WiFi settings and type a password by hand. Add
`--autojoin` and the script does the join AND probes the guitar's web
server itself, in the background, the instant it has credentials:

```bash
python jammy_ble.py --address 8C:F7:10:7A:8B:43 wifi --autojoin
```

**This machine's WiFi will switch away and back over ~10-15 seconds.**
Only run this on a device you don't need to stay connected right then --
a spare laptop, not the one you're in a call on. It automatically
reconnects to whatever network was active before it started.

## Safe first check (reads only, no pairing needed)

```bash
python jammy_ble.py scan
```

Finds the guitar, lists what it offers, reads the battery level. Confirmed
working already — the guitar has answered this every time.

## What we know about the guitar so far

- Bluetooth name: `Jammy461`, address `8C:F7:10:7A:8B:43`
- Firmware: 2.0.1, soundbank 1.2, serial `1903J31RB02461`
- It also answers over USB as a class-compliant MIDI device (`amidi -l`
  shows it) — that side is fully working already, no Bluetooth needed for
  basic playing or reading its version/name/serial/battery.
- Bluetooth side needs pairing (see above) before it will hand over WiFi
  credentials — everything else (browsing its services, reading battery)
  works over Bluetooth without pairing.

## If "scan" can't find the guitar

- Make sure the guitar is on and not connected to a phone.
- Find its Bluetooth address manually:

      bluetoothctl scan on
      # wait for a line with "Jammy" in it, note the AA:BB:CC:DD:EE:FF address
      # Ctrl-C, then:

      python jammy_ble.py scan --address AA:BB:CC:DD:EE:FF
