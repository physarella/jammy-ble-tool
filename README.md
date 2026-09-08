# Jammy G — Bluetooth tool

This talks to the Jammy guitar over Bluetooth. It can turn the guitar's built-in
WiFi network on and read its name + password, so we can get onto it.

It writes NOTHING to the guitar's firmware. It only reads, and switches the WiFi
on — the same thing the old app did. No risk to the guitar.

You need: Linux with Bluetooth, and Nix. (You're on NixOS, so you're set.)

## 1. Open a terminal in this folder

Unzip it, `cd` into the folder.

## 2. Make sure Bluetooth is on

    systemctl status bluetooth

If it's not running:

    sudo systemctl start bluetooth

## 3. Enter the tool's shell

    nix develop

If it complains about "experimental features", use this instead:

    nix --extra-experimental-features 'nix-command flakes' develop

The first time, it downloads Python + the Bluetooth library. Takes a minute.

## 4. Step one — safe check (reads only, changes nothing)

    python jammy_ble.py scan

This finds the guitar, connects, lists what it offers, and prints the battery.
Turn the guitar ON first. Copy everything it prints and send it back.

## 5. Step two — turn the guitar's WiFi on and get the login

    python jammy_ble.py wifi

Look in the output for a line saying WIFI_HOTSPOT_RESPONSE. It contains:
    n = the WiFi network name
    p = the WiFi password
    u = a URL     t = a token
Send that whole output back.

## If "scan" can't find the guitar

- Make sure the guitar is on and not connected to a phone.
- Find its Bluetooth address manually:

      bluetoothctl scan on
      # wait for a line with "Jammy" in it, note the AA:BB:CC:DD:EE:FF address
      # Ctrl-C, then:

      python jammy_ble.py scan --address AA:BB:CC:DD:EE:FF
