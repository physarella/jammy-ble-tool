#!/usr/bin/env python3
"""
Jammy G Bluetooth LE tool.

Protocol (recovered from the decompiled Android app com.playjammy 2.10.2):
  GATT main service : 9F3E05E2-2766-4C7D-B4C5-82C6124B803D
  message char      : 8401A4F1-7A76-42BD-98BB-DAD5D4A9F634   (write + notify)
  file-transfer char: F7CA6486-F81A-426E-A099-0C602CBB5DB2
  battery char      : 00002A19-0000-1000-8000-00805F9B34FB

  Wire format on the message char: byte[0] = message type, byte[1:] = UTF-8 JSON.

  Handshake, in the ORDER the real app does it (register must be first —
  the guitar rejects other commands with NOT_REGISTERED_DEVICE_ERROR otherwise;
  the app's own "ConnectRequestMessage" is dead code, never actually sent):
    -> REGISTER (21) {"c":{"t":<unix_seconds>}}
    <- REGISTER_RESPONSE (22) {...}   (or an error type)
  Turn the guitar's wifi hotspot on / read its login:
    -> WIFI_HOTSPOT_CHANGE (45) {"i":1}     (1=on, 2=off)
    -> WIFI_HOTSPOT_REQUEST (44)            (read current state)
    <- WIFI_HOTSPOT_RESPONSE (43) {"i":0/1,"c":{"n":ssid,"p":pass,"u":url,"t":token}}

  This tool only reads state and flips the wifi radio on -- exactly what the old
  app did during an update. It never writes firmware.
"""
import argparse, asyncio, json, subprocess, time
from bleak import BleakScanner, BleakClient

SVC   = "9f3e05e2-2766-4c7d-b4c5-82c6124b803d"
MSG   = "8401a4f1-7a76-42bd-98bb-dad5d4a9f634"
# Seen on the real hardware but NOT in the decompiled app -- not part of the
# known protocol, but it's notify-capable, so we listen on it too just in case
# newer firmware answers here instead. Purely observational: never written to.
MYSTERY = "7772e5db-3868-4112-a1a9-f2669d106bf3"
FILE  = "f7ca6486-f81a-426e-a099-0c602cbb5db2"
BATT  = "00002a19-0000-1000-8000-00805f9b34fb"

TYPES = {
    15:"BATTERY_STATUS", 18:"DISCONNECT", 20:"FINISH_SYNC",
    21:"REGISTER_REQUEST", 22:"REGISTER_RESPONSE", 23:"REGISTER_RESPONSE_ERROR",
    24:"CONNECTION_REQUEST", 25:"CONNECTION_RESPONSE_OK", 26:"CONNECTION_RESPONSE_ERROR",
    27:"NOT_REGISTERED_DEVICE_ERROR",
    43:"WIFI_HOTSPOT_RESPONSE", 44:"WIFI_HOTSPOT_REQUEST", 45:"WIFI_HOTSPOT_CHANGE",
    117:"DEBUG_MODE_LEAVE_ON_DISCONNECTED", 118:"DEBUG_MODE_LEAVE_ON_DISCONNECTED_REQUEST",
}

def decode(data: bytes):
    """Returns (printable_string, parsed_json_or_None, type_id)."""
    if not data:
        return "(empty)", None, None
    t = data[0]
    name = TYPES.get(t, f"type_{t}")
    body = data[1:]
    parsed = None
    try:
        txt = body.decode("utf-8")
        try:
            parsed = json.loads(txt)
            txt = json.dumps(parsed)
        except Exception:
            pass
    except Exception:
        txt = body.hex(" ")
    return f"[{t:>3}] {name:<28} {txt}", parsed, t

SLICE_SIZE = 32  # BLEHelperUtilKt.MTU_SIZE in the real app

def frame(t: int, payload=None) -> bytes:
    """byte0 = type, rest = UTF-8 JSON of payload (compact, like the app's Gson)."""
    if payload is None:
        return bytes([t])
    js = json.dumps(payload, separators=(",", ":"))
    return bytes([t]) + js.encode("utf-8")

def wrap_and_slice(payload: bytes) -> list:
    """Confirmed from the real app's bytecode (wrapBytes() + writeSliceData(),
    com/rnd64/ble/BLEHelperUtilKt): every outgoing message is wrapped as
    0xFF + payload + 0x00, then chopped into <=32-byte physical GATT writes.
    Our messages are all well under 32 bytes even wrapped, so this always
    returns exactly one chunk -- but it's implemented properly in case that
    ever changes."""
    framed = bytes([0xFF]) + payload + bytes([0x00])
    return [framed[i:i + SLICE_SIZE] for i in range(0, len(framed), SLICE_SIZE)]

async def find(address=None, timeout=12.0):
    print(f"scanning {timeout:.0f}s for the guitar ...")
    devs = await BleakScanner.discover(timeout=timeout)
    for d in devs:
        nm = d.name or ""
        if address and d.address.lower() == address.lower():
            return d
        if not address and ("jammy" in nm.lower()):
            print(f"  found {nm}  {d.address}")
            return d
    print("  devices seen:", [f"{(d.name or '?')}/{d.address}" for d in devs])
    return None

def make_notify_handler(seen: dict):
    # Mirrors handleSliceResponse() in the real app exactly: a notification
    # starting with 0xFF begins a message, one ending with 0x00 completes it,
    # and a single notification can be both (a whole message in one piece)
    # or neither (a middle chunk of a longer one). Confirmed from bytecode.
    buf = bytearray()
    def on_notify(_handle, data: bytearray):
        nonlocal buf
        data = bytes(data)
        if not data:
            return  # the empty notification BlueZ sends right on subscribe
        starts = data[0] == 0xFF
        ends = data[-1] == 0x00
        if starts and ends:
            complete, buf = data[1:-1], bytearray()
        elif starts:
            buf = bytearray(data[1:])
            return
        elif ends:
            buf += data[:-1]
            complete, buf = bytes(buf), bytearray()
        else:
            buf += data
            return
        if not complete:
            return
        seen["count"] = seen.get("count", 0) + 1
        text, parsed, t = decode(complete)
        print("  <-", text)
        if t == 43 and isinstance(parsed, dict):
            seen["hotspot"] = parsed          # {"i":..,"c":{"n":..,"p":..,"u":..,"t":..}}
        if t in (23, 26, 27):
            seen["error"] = t
    return on_notify

async def writer(client, response):
    async def send(t, payload=None, label=""):
        b = frame(t, payload)
        print(f"  -> [{t:>3}] {TYPES.get(t,'?'):<24} {b[1:].decode('utf-8','replace')!r}  ({label})")
        for chunk in wrap_and_slice(b):
            await client.write_gatt_char(MSG, chunk, response=response)
        await asyncio.sleep(1.5)
    return send

async def cmd_scan(args):
    d = await find(args.address)
    if not d:
        print("guitar not found. Is it on? Is bluetooth up (systemctl status bluetooth)?")
        return
    async with BleakClient(d) as c:
        print(f"connected: {d.address}  mtu={getattr(c,'mtu_size','?')}\n")
        for s in c.services:
            print(f"service {s.uuid}")
            for ch in s.characteristics:
                print(f"    char {ch.uuid}  {ch.properties}")
        try:
            b = await c.read_gatt_char(BATT)
            print(f"\nbattery: {int(b[0])}%")
        except Exception as e:
            print("battery read failed:", e)

def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

async def _active_wifi_connection_name():
    """The nmcli connection PROFILE name currently active on wifi, if any --
    so we can switch back to exactly this after probing, rather than leaving
    whoever's machine this is stuck on the guitar's isolated network."""
    try:
        r = await asyncio.to_thread(
            _run, ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"], 8
        )
        for line in r.stdout.splitlines():
            name, _, kind = line.rpartition(":")
            if "wireless" in kind:
                return name
    except Exception:
        pass
    return None

async def join_and_probe(ssid: str, password: str, url: str):
    """The guitar's hotspot only stays up ~15-20s if nothing joins it -- too
    fast for a human to alt-tab, open wifi settings, and type. This does the
    join + probe itself, in the background, the instant credentials are known,
    so it happens in ~1-2s instead, then switches back to whatever wifi
    network was active before, so the machine running this isn't left
    stranded on the guitar's internet-less network. Reuses nmcli/curl
    (already confirmed on this machine) rather than adding new dependencies."""
    original = await _active_wifi_connection_name()
    if original:
        print(f"[auto] (will reconnect to '{original}' when done)")

    print(f"\n[auto] joining wifi '{ssid}' ...")
    try:
        r = await asyncio.to_thread(
            _run, ["nmcli", "dev", "wifi", "connect", ssid, "password", password], 20
        )
        out = (r.stdout or "") + (r.stderr or "")
        print("[auto] nmcli:", out.strip() or f"(exit code {r.returncode})")
        if r.returncode != 0:
            print("[auto] join failed -- too slow, or wrong network in range? stopping here.")
            return
    except Exception as e:
        print(f"[auto] nmcli failed: {e}")
        return

    try:
        print(f"[auto] probing {url} ...")
        r = await asyncio.to_thread(_run, ["curl", "-m", "8", "-sS", "-v", url], 15)
        print("[auto] --- curl connection trace ---")
        print(r.stderr)
        print("[auto] --- response body ---")
        print(r.stdout or "(empty body)")
    except Exception as e:
        print(f"[auto] probe failed: {e}")
    finally:
        if original:
            print(f"[auto] reconnecting to '{original}' ...")
            try:
                r = await asyncio.to_thread(_run, ["nmcli", "connection", "up", original], 15)
                print("[auto]", (r.stdout or r.stderr).strip() or f"(exit code {r.returncode})")
            except Exception as e:
                print(f"[auto] reconnect failed -- you may need to rejoin your wifi manually: {e}")

async def cmd_wifi(args):
    d = await find(args.address)
    if not d:
        print("guitar not found.")
        return
    seen = {}
    async with BleakClient(d) as c:
        print(f"connected: {d.address}  mtu={getattr(c,'mtu_size','?')}")
        await asyncio.sleep(1.0)   # let the connection settle before touching GATT

        seen["count"] = 0
        try:
            await c.start_notify(MSG, make_notify_handler(seen))
            print("notifications enabled (message channel): ok")
        except Exception as e:
            print(f"notifications enabled (message channel): FAILED -- {e}")
            print("Stopping here -- send this whole output back.")
            return

        # Best-effort: also listen on the unlisted channel found on the real
        # hardware, purely to rule it in/out. Never written to.
        mystery_active = False
        try:
            def on_mystery(_h, data: bytearray):
                seen["count"] = seen.get("count", 0) + 1
                print(f"  <- MYSTERY {bytes(data).hex(' ') or '(empty)'}")
            await c.start_notify(MYSTERY, on_mystery)
            mystery_active = True
            print("notifications enabled (mystery channel): ok")
        except Exception as e:
            print(f"notifications enabled (mystery channel): skipped -- {e}")

        # Sanity read right after subscribing -- proves the characteristic
        # itself is reachable, independent of whether notify ever fires.
        try:
            b = await c.read_gatt_char(MSG)
            print(f"initial read of message channel: {bytes(b).hex(' ') or '(empty)'}")
        except Exception as e:
            print(f"initial read of message channel failed: {e}")

        # Best-effort: ask BlueZ what MTU actually got negotiated on the wire.
        # bleak's own mtu_size can be stale/unqueried (hence its warning) --
        # this is the real number, if bleak's backend exposes it.
        try:
            real_mtu = await c._backend._acquire_mtu()
            print(f"actual negotiated MTU (queried from BlueZ): {real_mtu}")
        except Exception as e:
            print(f"could not query the real MTU (non-fatal): {e}")

        # Always write WITH response. Our messages are 20-30 bytes but the
        # default BLE packet is only 20 bytes usable -- write-with-response
        # lets the stack split the message automatically. Write-without-response
        # has no such splitting and silently drops anything too big.
        send = await writer(c, response=True)

        # REGISTER MUST BE FIRST. The guitar rejects everything else until this
        # succeeds (that's what NOT_REGISTERED_DEVICE_ERROR / type 27 means).
        print("\n--- register (must happen before any other command) ---")
        await send(21, {"c": {"t": int(time.time())}}, "REGISTER")
        await asyncio.sleep(2.5)
        if seen.get("error"):
            print(f"\nGuitar rejected registration (error type {seen['error']}).")
            print("Stopping here -- send this whole output back before trying anything else.")
            await c.stop_notify(MSG)
            if mystery_active:
                await c.stop_notify(MYSTERY)
            return

        print("\n--- turn wifi ON ---")
        await send(45, {"i": 1}, "WIFI_HOTSPOT_CHANGE on")

        # Off by default -- this machine's network is NOT touched unless you
        # explicitly pass --autojoin (see the top-level docstring / README).
        # When on: the hotspot only stays up ~15-20s if nothing joins it, so
        # the join+probe fires THE INSTANT we have credentials, in the
        # background, rather than waiting for the rest of this function.
        probe_task = None
        hotspot = seen.get("hotspot")
        if hotspot and args.autojoin:
            creds = hotspot.get("c") or {}
            ssid, pw, url = creds.get("n"), creds.get("p"), creds.get("u")
            if ssid and pw and url:
                probe_task = asyncio.create_task(join_and_probe(ssid, pw, url))

        print("\n--- keep it on after we disconnect (default is OFF -- the guitar")
        print("    normally tears the hotspot down the moment BLE drops) ---")
        await send(117, {"i": 1}, "DEBUG_MODE_LEAVE_ON_DISCONNECTED enable")
        print("\n--- read the login ---")
        await send(44, None, "WIFI_HOTSPOT_REQUEST")

        if probe_task:
            await probe_task
        else:
            await asyncio.sleep(5.0)

        print(f"\nnotifications received this session (both channels): {seen['count']}")
        await c.stop_notify(MSG)
        if mystery_active:
            await c.stop_notify(MYSTERY)

        hotspot = seen.get("hotspot")
        if not hotspot:
            print("\nNo WIFI_HOTSPOT_RESPONSE seen. Send this whole output back.")
            return
        creds = hotspot.get("c") or {}
        ssid = creds.get("n"); pw = creds.get("p")
        print(f"\nWiFi is {'ON' if hotspot.get('i') == 1 else 'off'}")
        print(f"  network : {ssid}")
        print(f"  password: {pw}")
        print(f"  url     : {creds.get('u')}")
        print(f"  token   : {creds.get('t')}")
        if ssid and pw:
            print("\nTo join that network from this machine, run:")
            print(f"\n    nmcli dev wifi connect '{ssid}' password '{pw}'\n")
            print("(if nmcli isn't available, use your desktop's wifi menu with the")
            print(" same network name and password)")

        if args.hold:
            # We already sent DEBUG_MODE_LEAVE_ON_DISCONNECTED earlier, but
            # the hotspot has still been observed dying after ~15-20s anyway
            # -- this tests directly whether keeping the BLE link open (not
            # just having sent that flag) is what actually keeps it alive,
            # instead of guessing at another opcode.
            print("\n[hold] Keeping this Bluetooth connection open on purpose,")
            print("[hold] to test whether that's what keeps the hotspot up.")
            print("[hold] Go join the WiFi network now -- you have as long as")
            print("[hold] this keeps running. Press Ctrl+C here when you're done.")
            try:
                while True:
                    await asyncio.sleep(3600)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n[hold] stopping -- disconnecting now.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "wifi"])
    ap.add_argument("--address", help="BLE MAC, if name scan doesn't find it")
    ap.add_argument("--autojoin", action="store_true",
                     help="join the guitar's hotspot and probe its web server "
                          "automatically. This machine's network WILL switch "
                          "away and back -- only use on a device you don't "
                          "need to stay connected (not one on a call, etc).")
    ap.add_argument("--hold", action="store_true",
                     help="after printing the WiFi login, keep the Bluetooth "
                          "connection open (don't let the script exit) so you "
                          "have unlimited time to join it from another device. "
                          "Ctrl+C to disconnect when done.")
    args = ap.parse_args()
    try:
        asyncio.run(cmd_scan(args) if args.cmd == "scan" else cmd_wifi(args))
    except EOFError:
        # The guitar drops the BLE link itself once its WiFi hotspot comes up
        # (it can't run both radios the same way at once). By this point
        # everything we needed has already printed -- this is just our own
        # script's polite goodbye landing on a connection that's already gone.
        pass

if __name__ == "__main__":
    main()
