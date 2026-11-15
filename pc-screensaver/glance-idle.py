#!/usr/bin/env python3
"""Show the Glance dashboard fullscreen after N minutes of idle, hide it on activity.

The GNOME/Wayland equivalent of the Mac's WebViewScreenSaver setup: Mutter's
IdleMonitor gives us the idle/active edges, and we park a kiosk Chrome window on
the dashboard in between. Runs as the user unit glance-idle.service.
"""
import os
import signal
import subprocess
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

IDLE_MS = int(float(os.environ.get("GLANCE_IDLE_MINUTES", "15")) * 60 * 1000)
URL = os.environ.get("GLANCE_URL", "http://localhost:8090/")
PROFILE = os.path.expanduser("~/.cache/glance-idle-chrome")
DRY_RUN = "--dry-run" in sys.argv

proc = None


def log(msg):
    print(msg, flush=True)


def idle_inhibited(bus):
    """True if something (a video player, a game) asked us not to idle."""
    try:
        sm = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.SessionManager", "/org/gnome/SessionManager",
            "org.gnome.SessionManager", None)
        return bool(sm.call_sync("IsInhibited", GLib.Variant("(u)", (8,)),
                                 Gio.DBusCallFlags.NONE, 2000, None).unpack()[0])
    except GLib.Error as e:
        log(f"inhibit check failed, assuming not inhibited: {e.message}")
        return False


def show(bus):
    global proc
    if proc and proc.poll() is None:
        return
    if idle_inhibited(bus):
        log("idle but something is inhibiting (video/game?) - not showing")
        return
    cmd = ["/usr/bin/google-chrome", f"--user-data-dir={PROFILE}",
           "--kiosk", "--no-first-run", "--no-default-browser-check",
           "--disable-session-crashed-bubble", "--disable-infobars",
           f"--app={URL}"]
    log(f"idle -> showing dashboard: {URL}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hide():
    global proc
    if proc and proc.poll() is None:
        log("active -> hiding dashboard")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    proc = None


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    mon = Gio.DBusProxy.new_sync(
        bus, Gio.DBusProxyFlags.NONE, None,
        "org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
        "org.gnome.Mutter.IdleMonitor", None)

    idle_id = mon.call_sync("AddIdleWatch", GLib.Variant("(t)", (IDLE_MS,)),
                            Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    log(f"watching for {IDLE_MS // 60000} min idle (watch {idle_id}), url {URL}")

    if DRY_RUN:
        idle_now = mon.call_sync("GetIdletime", None, Gio.DBusCallFlags.NONE,
                                 2000, None).unpack()[0]
        log(f"dry-run OK: idle monitor reachable, current idle {idle_now // 1000}s, "
            f"inhibited={idle_inhibited(bus)}, chrome={os.path.exists('/usr/bin/google-chrome')}")
        return 0

    state = {"active_id": None}

    def on_signal(_proxy, _sender, signal_name, params):
        if signal_name != "WatchFired":
            return
        fired = params.unpack()[0]
        if fired == idle_id:
            show(bus)
            if proc:
                state["active_id"] = mon.call_sync(
                    "AddUserActiveWatch", None, Gio.DBusCallFlags.NONE,
                    2000, None).unpack()[0]
        elif fired == state["active_id"]:
            state["active_id"] = None   # user-active watches are one-shot
            hide()

    mon.connect("g-signal", on_signal)

    loop = GLib.MainLoop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig,
                             lambda: (hide(), loop.quit(), False)[2])
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
