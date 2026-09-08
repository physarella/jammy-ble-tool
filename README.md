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

## How to pair the guitar (found 2026-09-07)

**Turn the guitar on, then press and hold the Volume KNOB (push straight in
on it, it's a knob not a button) for 5 seconds.**

Watch for this: **the Power button starts blinking blue.** That's the
confirmation it worked and the guitar is now open for pairing. If it doesn't
blink blue, the hold didn't register — try again.

The pairing window is short once it starts blinking, so run the pairing
command right away, don't wait around.

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

(Replace the address if it's a different guitar — find it with
`python jammy_ble.py scan`.)

Takes about 20 seconds total, that's normal. Watch for the line right after
"Attempting to pair" — should say "Pairing successful."

### STATUS as of 2026-09-07: pairing not yet confirmed working

We know the button-hold + blue blink is needed. We have NOT yet seen a
successful pair. Next session: try the button hold, watch for the blue
light, then immediately run the pairing block above and see what it says.

## Once paired: get the WiFi login

```bash
python jammy_ble.py --address 8C:F7:10:7A:8B:43 wifi
```

This registers with the guitar, turns its WiFi on, and reads back the
network name + password. If it finds them it prints a ready-to-run `nmcli`
command to join that network.

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
