#!/usr/bin/env python3
# irlos-installer.py
# GPL-3.0 — Ethan Manners
#
# Archinstall-style TUI installer for Irlos IRL stream server OS.
# Runs on first boot, configures everything, then installs.

import argparse
import curses
import subprocess
import os
import sys
import json
import time

CONFIG_PATH = "/etc/irlos/config.json"
DONE_FLAG   = "/etc/irlos/.setup_complete"
LOG_PATH    = "/var/log/irlos-install.log"

# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_CFG = {
    "hostname":        "irlos-server",
    "net_mode":        "ethernet",   # ethernet | wifi
    "wifi_ssid":       "",
    "wifi_pass":       "",
    "nvidia_version":  "570.144.03",
    "resolution":      "1920x1080",
    "fps":             "60",
    "platform":        "Kick",
    "stream_key":      "",
    "bitrate":         "6000",
    "relay_proto":     "SRT",        # SRT | RTMP
    "relay_host":      "",
    "relay_port":      "9000",
    "relay_streamid":  "",           # SRT: ?streamid=x/x/x
    "relay_app":       "",           # RTMP: application name
    "relay_stream":    "",           # RTMP: stream name
    "noalbs_platform": "kick",
    "noalbs_user":     "",
    "noalbs_low":      "2000",
    "noalbs_offline":  "500",
    "ssh_pubkey":      "",
    "vnc_pass":        "",
}

NVIDIA_VERSIONS = [
    "570.144.03",
    "565.77",
    "550.144.03",
    "535.230.02",
    "525.147.05",
]

RESOLUTIONS  = ["1920x1080", "1280x720", "2560x1440", "3840x2160"]
FPS_OPTIONS  = ["60", "30"]
PLATFORMS    = ["Kick", "Twitch", "YouTube", "Custom RTMP"]
RELAY_PROTOS = ["SRT", "RTMP"]

# ─── Color pairs ──────────────────────────────────────────────────────────────

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN,  -1)               # header / accent
    curses.init_pair(2, curses.COLOR_WHITE, -1)               # normal text
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN) # selected row
    curses.init_pair(4, curses.COLOR_YELLOW,-1)               # label / value
    curses.init_pair(5, curses.COLOR_GREEN, -1)               # done / success
    curses.init_pair(6, curses.COLOR_RED,   -1)               # error
    curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE) # button

HDR  = lambda: curses.color_pair(1) | curses.A_BOLD
NRM  = lambda: curses.color_pair(2)
SEL  = lambda: curses.color_pair(3) | curses.A_BOLD
LBL  = lambda: curses.color_pair(4)
DONE = lambda: curses.color_pair(5)
ERR  = lambda: curses.color_pair(6)
BTN  = lambda: curses.color_pair(7) | curses.A_BOLD

# ─── UI primitives ────────────────────────────────────────────────────────────

def center_x(w, text):
    return max(0, (w - len(text)) // 2)

def draw_header(stdscr, title="IRLOS Installer"):
    h, w = stdscr.getmaxyx()
    stdscr.attron(HDR())
    stdscr.addstr(0, 0, " " * (w - 1))
    stdscr.addstr(0, center_x(w, title), title)
    stdscr.attroff(HDR())

def draw_footer(stdscr, msg="[↑↓] Navigate  [Enter] Select  [q] Quit"):
    h, w = stdscr.getmaxyx()
    stdscr.attron(HDR())
    stdscr.addstr(h - 1, 0, msg[:w - 1].ljust(w - 1))
    stdscr.attroff(HDR())

def input_box(stdscr, prompt, default="", password=False):
    """Single-line input popup. Returns entered string."""
    h, w = stdscr.getmaxyx()
    bh, bw = 7, min(72, w - 4)
    by = (h - bh) // 2
    bx = (w - bw) // 2

    win = curses.newwin(bh, bw, by, bx)
    win.keypad(True)
    win.border()
    win.attron(HDR())
    win.addstr(0, 2, f" {prompt[:bw-4]} ")
    win.attroff(HDR())
    if default and not password:
        win.addstr(2, 2, f"Default: {default}"[:bw - 4], NRM())
    win.addstr(4, 2, "> ", LBL())
    win.refresh()

    curses.curs_set(1)
    buf = list(default if not password else "")
    cx  = len(buf)
    fx  = 4   # field x start
    fw  = bw - 6

    while True:
        display = ("*" * len(buf)) if password else "".join(buf)
        win.addstr(4, fx, " " * fw)
        win.addstr(4, fx, display[:fw])
        win.move(4, fx + min(cx, fw - 1))
        win.refresh()
        ch = win.getch()
        if ch in (10, 13):
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if cx > 0:
                buf.pop(cx - 1)
                cx -= 1
        elif ch == curses.KEY_LEFT:
            cx = max(0, cx - 1)
        elif ch == curses.KEY_RIGHT:
            cx = min(len(buf), cx + 1)
        elif 32 <= ch <= 126:
            buf.insert(cx, chr(ch))
            cx += 1

    curses.curs_set(0)
    del win
    stdscr.touchwin()
    stdscr.refresh()
    return "".join(buf)

def choice_menu(stdscr, title, options, current=0):
    """Popup selection menu. Returns selected index."""
    h, w   = stdscr.getmaxyx()
    bw     = min(max(len(o) for o in options) + 6, w - 4)
    bh     = min(len(options) + 4, h - 4)
    by     = (h - bh) // 2
    bx     = (w - bw) // 2
    win    = curses.newwin(bh, bw, by, bx)
    win.keypad(True)
    idx    = current

    while True:
        win.clear()
        win.border()
        win.attron(HDR())
        win.addstr(0, 2, f" {title[:bw-4]} ")
        win.attroff(HDR())
        visible = options[:bh - 4]
        for i, opt in enumerate(visible):
            if i == idx:
                win.attron(SEL())
                win.addstr(i + 2, 2, f" {opt:<{bw - 5}} ")
                win.attroff(SEL())
            else:
                win.addstr(i + 2, 2, f" {opt} ", NRM())
        win.refresh()
        ch = win.getch()
        if ch == curses.KEY_UP:
            idx = (idx - 1) % len(options)
        elif ch == curses.KEY_DOWN:
            idx = (idx + 1) % len(options)
        elif ch in (10, 13):
            break
        elif ch == ord('q'):
            idx = current
            break

    del win
    stdscr.touchwin()
    stdscr.refresh()
    return idx

def confirm(stdscr, msg):
    """Yes / No popup. Returns True for Yes."""
    h, w  = stdscr.getmaxyx()
    bw    = min(len(msg) + 8, w - 4)
    bh    = 5
    by    = (h - bh) // 2
    bx    = (w - bw) // 2
    win   = curses.newwin(bh, bw, by, bx)
    win.keypad(True)
    sel   = 0

    while True:
        win.clear()
        win.border()
        win.addstr(1, 2, msg[:bw - 4], NRM())
        for i, label in enumerate(["  Yes  ", "  No   "]):
            attr = BTN() if i == sel else NRM()
            win.addstr(3, 4 + i * 10, label, attr)
        win.refresh()
        ch = win.getch()
        if ch in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
            sel = 1 - sel
        elif ch in (10, 13):
            break

    del win
    stdscr.touchwin()
    stdscr.refresh()
    return sel == 0

# ─── Main menu ────────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("Hostname",           "hostname"),
    ("Network / WiFi",     "network"),
    ("NVIDIA Driver",      "nvidia"),
    ("Xorg + Openbox",     "xorg"),
    ("OBS Studio",         "obs"),
    ("noalbs",             "noalbs"),
    ("x11vnc / VNC",       "vnc"),
    ("OBS Stream Config",  "obs_config"),
    ("noalbs Config",      "noalbs_config"),
    ("SSH Key",            "ssh"),
    ("Autostart",          "autostart"),
    ("Review & Install",   "install"),
]

def cfg_summary(cfg, key):
    m = {
        "hostname":      cfg.get("hostname", ""),
        "network":       cfg["net_mode"].upper() + (f": {cfg['wifi_ssid']}" if cfg["net_mode"] == "wifi" else ""),
        "nvidia":        cfg.get("nvidia_version", ""),
        "xorg":          f"{cfg.get('resolution','')} @ {cfg.get('fps','')}fps",
        "obs":           cfg.get("platform", ""),
        "noalbs":        cfg.get("noalbs_platform", "") + (f" / {cfg['noalbs_user']}" if cfg.get("noalbs_user") else ""),
        "vnc":           "configured" if cfg.get("vnc_pass") else "not set",
        "obs_config":    f"{cfg.get('bitrate','')}kbps  {cfg.get('relay_proto','')}  {cfg.get('relay_host','')}:{cfg.get('relay_port','')}",
        "noalbs_config": f"low:{cfg.get('noalbs_low','')}  offline:{cfg.get('noalbs_offline','')}",
        "ssh":           "key set" if cfg.get("ssh_pubkey") else "password auth",
        "autostart":     "systemd + openbox",
        "install":       "← configure all items above first",
    }
    return m.get(key, "")

def draw_main_menu(stdscr, cfg, cursor, completed):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr)
    draw_footer(stdscr)

    col_w = 24
    for i, (label, key) in enumerate(MENU_ITEMS):
        row    = 2 + i
        prefix = "✓ " if key in completed else "  "
        line   = f"{prefix}{label}"
        summ   = cfg_summary(cfg, key)

        if i == cursor:
            stdscr.attron(SEL())
            stdscr.addstr(row, 1, f" {line:<{col_w}} ")
            stdscr.attroff(SEL())
        else:
            attr = DONE() if key in completed else NRM()
            stdscr.addstr(row, 1, f" {line:<{col_w}} ", attr)

        if summ and col_w + 6 < w:
            stdscr.addstr(row, col_w + 4, summ[:w - col_w - 6], LBL())

    stdscr.addstr(2,  col_w + 4, "IRLOS — IRL Stream Server OS", HDR())
    stdscr.addstr(3,  col_w + 4, "GPL-3.0", NRM())
    stdscr.addstr(5,  col_w + 4, "Configure each item above,", NRM())
    stdscr.addstr(6,  col_w + 4, "then select Review & Install.", NRM())
    stdscr.refresh()

# ─── Config screens ───────────────────────────────────────────────────────────

def screen_hostname(stdscr, cfg):
    val = input_box(stdscr, "Hostname", default=cfg["hostname"])
    if val:
        cfg["hostname"] = val

def screen_network(stdscr, cfg):
    idx = choice_menu(stdscr, "Network Mode",
                      ["Ethernet (wired)", "WiFi"],
                      current=0 if cfg["net_mode"] == "ethernet" else 1)
    if idx == 0:
        cfg["net_mode"] = "ethernet"
    else:
        cfg["net_mode"] = "wifi"
        ssid = input_box(stdscr, "WiFi SSID", default=cfg["wifi_ssid"])
        cfg["wifi_ssid"] = ssid
        pw   = input_box(stdscr, "WiFi Password", password=True)
        cfg["wifi_pass"] = pw

def screen_nvidia(stdscr, cfg):
    # Detect GPU and show it
    result   = subprocess.run("lspci | grep -i nvidia", shell=True, capture_output=True, text=True)
    gpu_str  = result.stdout.strip().split("\n")[0] if result.stdout.strip() else "No NVIDIA GPU detected"
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr)
    stdscr.addstr(2, 2, "Detected GPU:", LBL())
    stdscr.addstr(2, 16, gpu_str[:w - 18], NRM())
    stdscr.addstr(4, 2, "Select driver version to install via .run:", NRM())
    stdscr.refresh()
    time.sleep(0.4)
    cur = NVIDIA_VERSIONS.index(cfg["nvidia_version"]) if cfg["nvidia_version"] in NVIDIA_VERSIONS else 0
    idx = choice_menu(stdscr, "NVIDIA Driver Version", NVIDIA_VERSIONS, current=cur)
    cfg["nvidia_version"] = NVIDIA_VERSIONS[idx]

def screen_xorg(stdscr, cfg):
    cur = RESOLUTIONS.index(cfg["resolution"]) if cfg["resolution"] in RESOLUTIONS else 0
    idx = choice_menu(stdscr, "Output Resolution", RESOLUTIONS, current=cur)
    cfg["resolution"] = RESOLUTIONS[idx]
    cur = FPS_OPTIONS.index(cfg["fps"]) if cfg["fps"] in FPS_OPTIONS else 0
    idx = choice_menu(stdscr, "FPS", FPS_OPTIONS, current=cur)
    cfg["fps"] = FPS_OPTIONS[idx]

def screen_obs(stdscr, cfg):
    cur = PLATFORMS.index(cfg["platform"]) if cfg["platform"] in PLATFORMS else 0
    idx = choice_menu(stdscr, "Streaming Platform", PLATFORMS, current=cur)
    cfg["platform"] = PLATFORMS[idx]
    key = input_box(stdscr, f"{cfg['platform']} Stream Key", password=True)
    if key:
        cfg["stream_key"] = key

def screen_noalbs(stdscr, cfg):
    platforms = ["kick", "twitch"]
    cur = platforms.index(cfg["noalbs_platform"]) if cfg["noalbs_platform"] in platforms else 0
    idx = choice_menu(stdscr, "noalbs Platform", platforms, current=cur)
    cfg["noalbs_platform"] = platforms[idx]
    user = input_box(stdscr, "Channel Username", default=cfg["noalbs_user"])
    if user:
        cfg["noalbs_user"] = user

def screen_vnc(stdscr, cfg):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr)
    stdscr.addstr(2, 2, "VNC binds to localhost only.", LBL())
    stdscr.addstr(3, 2, "Remote access: ssh -L 5901:localhost:5901 irlos@<server>", NRM())
    stdscr.addstr(4, 2, "Then connect your VNC client to localhost:5901", NRM())
    stdscr.refresh()
    time.sleep(0.5)
    pw = input_box(stdscr, "VNC Password (min 6 chars)", password=True)
    if pw:
        cfg["vnc_pass"] = pw

def screen_obs_config(stdscr, cfg):
    br = input_box(stdscr, "Video Bitrate (kbps)", default=cfg["bitrate"])
    if br:
        cfg["bitrate"] = br

    cur   = RELAY_PROTOS.index(cfg["relay_proto"]) if cfg["relay_proto"] in RELAY_PROTOS else 0
    idx   = choice_menu(stdscr, "Relay Input Protocol", RELAY_PROTOS, current=cur)
    cfg["relay_proto"] = RELAY_PROTOS[idx]

    host  = input_box(stdscr, "Relay Server IP / Hostname", default=cfg["relay_host"])
    if host:
        cfg["relay_host"] = host

    port  = input_box(stdscr, "Relay Server Port", default=cfg["relay_port"])
    if port:
        cfg["relay_port"] = port

    if cfg["relay_proto"] == "SRT":
        sid = input_box(stdscr,
                        "SRT Stream ID  (e.g. live/mystream/publish)",
                        default=cfg["relay_streamid"])
        cfg["relay_streamid"] = sid
    else:
        app = input_box(stdscr, "RTMP Application Name  (e.g. live)", default=cfg["relay_app"])
        cfg["relay_app"] = app
        st  = input_box(stdscr, "RTMP Stream Name", default=cfg["relay_stream"])
        cfg["relay_stream"] = st

def screen_noalbs_config(stdscr, cfg):
    low = input_box(stdscr, "Switch to BRB below (kbps)", default=cfg["noalbs_low"])
    if low:
        cfg["noalbs_low"] = low
    off = input_box(stdscr, "Switch to Offline below (kbps)", default=cfg["noalbs_offline"])
    if off:
        cfg["noalbs_offline"] = off

def screen_ssh(stdscr, cfg):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr)
    stdscr.addstr(2, 2, "Paste your SSH public key (ed25519 recommended).", LBL())
    stdscr.addstr(3, 2, "Leave blank to keep password auth enabled.", NRM())
    stdscr.refresh()
    key = input_box(stdscr, "SSH Public Key  (blank to skip)")
    cfg["ssh_pubkey"] = key

def screen_autostart(stdscr, cfg):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr)
    stdscr.addstr(2, 2, "The following will be wired up automatically:", LBL())
    stdscr.addstr(4, 2, "  irlos-session.service   Xorg + Openbox on boot", NRM())
    stdscr.addstr(5, 2, "  irlos-vnc.service       x11vnc bound to localhost:5901", NRM())
    stdscr.addstr(6, 2, "  openbox autostart       OBS --startstreaming + noalbs", NRM())
    stdscr.addstr(8, 2, "Press Enter to confirm.", LBL())
    stdscr.refresh()
    stdscr.getch()

# ─── Install helpers ──────────────────────────────────────────────────────────

def build_relay_url(cfg):
    if cfg["relay_proto"] == "SRT":
        url = f"srt://{cfg['relay_host']}:{cfg['relay_port']}"
        if cfg.get("relay_streamid"):
            url += f"?streamid={cfg['relay_streamid']}"
        return url
    return f"rtmp://{cfg['relay_host']}:{cfg['relay_port']}/{cfg['relay_app']}/{cfg['relay_stream']}"

def write_obs_scene(cfg):
    os.makedirs("/home/irlos/.config/obs-studio/basic/scenes", exist_ok=True)
    relay_url = build_relay_url(cfg)
    scene = {
        "current_scene": "Live",
        "current_program_scene": "Live",
        "scenes": [
            {
                "name": "Live",
                "sources": [
                    {
                        "id": "ffmpeg_source",
                        "name": "Relay Input",
                        "settings": {
                            "input": relay_url,
                            "is_local_file": False,
                            "restart_on_activate": True,
                            "buffering_mb": 2
                        }
                    }
                ]
            },
            {"name": "BRB",     "sources": []},
            {"name": "Offline", "sources": []},
        ]
    }
    with open("/home/irlos/.config/obs-studio/basic/scenes/irlos.json", "w") as f:
        json.dump(scene, f, indent=2)

def write_obs_profile(cfg):
    os.makedirs("/home/irlos/.config/obs-studio/basic/profiles/irlos", exist_ok=True)
    rtmp_servers = {
        "Kick":        "rtmp://fa723fc1b171.global-contribute.live-video.net/app",
        "Twitch":      "rtmp://live.twitch.tv/app",
        "YouTube":     "rtmp://a.rtmp.youtube.com/live2",
        "Custom RTMP": "",
    }
    server  = rtmp_servers.get(cfg["platform"], "")
    ow, oh  = cfg["resolution"].split("x")
    basic   = f"""[Video]
BaseCX={ow}
BaseCY={oh}
OutputCX={ow}
OutputCY={oh}
FPSType=0
FPSCommon={cfg['fps']}

[Output]
Mode=Simple

[SimpleOutput]
VBitrate={cfg['bitrate']}
StreamEncoder=obs_nvenc_h264_tex
ABitrate=160

[Stream1]
server={server}
key={cfg['stream_key']}
"""
    with open("/home/irlos/.config/obs-studio/basic/profiles/irlos/basic.ini", "w") as f:
        f.write(basic)

    with open("/home/irlos/.config/obs-studio/global.ini", "w") as f:
        f.write("[General]\nCurrentProfile=irlos\nCurrentSceneCollection=irlos\n")

def write_noalbs_config(cfg):
    os.makedirs("/home/irlos/.config/noalbs", exist_ok=True)
    config = {
        "chat": {"platform": cfg["noalbs_platform"], "username": cfg["noalbs_user"]},
        "switcher": {
            "bitrateSwitcherEnabled": True,
            "onlySwitchWhenStreaming": True,
            "instantlySwitchOnRecover": True,
            "autoSwitchNotification": True,
            "scenes": {"normal": "Live", "low": "BRB", "offline": "Offline"},
            "bitrate": {
                "switchingThreshold": int(cfg["noalbs_low"]),
                "offlineThreshold":   int(cfg["noalbs_offline"])
            }
        },
        "software": {"type": "Obs", "host": "localhost", "port": 4455, "password": ""}
    }
    with open("/home/irlos/.config/noalbs/config.json", "w") as f:
        json.dump(config, f, indent=2)

def write_xorg_conf(cfg):
    os.makedirs("/etc/X11", exist_ok=True)
    ow, oh = cfg["resolution"].split("x")
    xconf = f"""Section "ServerLayout"
    Identifier "Layout0"
    Screen 0 "Screen0"
EndSection

Section "Device"
    Identifier  "Device0"
    Driver      "nvidia"
    Option      "AllowEmptyInitialConfiguration" "true"
EndSection

Section "Monitor"
    Identifier  "Monitor0"
    HorizSync   28-80
    VertRefresh 48-75
EndSection

Section "Screen"
    Identifier   "Screen0"
    Device       "Device0"
    Monitor      "Monitor0"
    DefaultDepth 24
    SubSection "Display"
        Depth  24
        Modes  "{ow}x{oh}"
    EndSubSection
EndSection
"""
    with open("/etc/X11/xorg.conf", "w") as f:
        f.write(xconf)

def write_systemd_units():
    session = """[Unit]
Description=Irlos Stream Session
After=network.target

[Service]
User=irlos
Type=simple
ExecStart=/usr/bin/startx /usr/bin/openbox-session -- :0 vt1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    vnc = """[Unit]
Description=Irlos VNC (localhost only)
After=irlos-session.service

[Service]
User=irlos
Environment=DISPLAY=:0
ExecStart=/usr/bin/x11vnc -display :0 -rfbauth /home/irlos/.vnc/passwd -rfbport 5901 -localhost -forever -noxdamage -shared
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    with open("/etc/systemd/system/irlos-session.service", "w") as f:
        f.write(session)
    with open("/etc/systemd/system/irlos-vnc.service", "w") as f:
        f.write(vnc)

def write_openbox_autostart():
    os.makedirs("/home/irlos/.config/openbox", exist_ok=True)
    with open("/home/irlos/.config/openbox/autostart", "w") as f:
        f.write("#!/bin/bash\nobs --startstreaming --minimize-to-tray &\nsleep 5\nnoalbs &\n")
    os.chmod("/home/irlos/.config/openbox/autostart", 0o755)

# ─── Install phase ────────────────────────────────────────────────────────────

INSTALL_STEPS = [
    "Set hostname",
    "Configure network",
    "Download NVIDIA .run",
    "Install NVIDIA driver",
    "Install Xorg + Openbox",
    "Install OBS Studio",
    "Install noalbs",
    "Install x11vnc",
    "Write Xorg config (dummy plug)",
    "Write OBS scene + profile",
    "Write noalbs config",
    "Configure SSH",
    "Set VNC password",
    "Write systemd units",
    "Write Openbox autostart",
    "Save config",
    "Complete",
]

def draw_install(stdscr, steps, current, log_lines):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "IRLOS — Installing")
    for i, step in enumerate(steps):
        row = 2 + i
        if row >= h - 7:
            break
        if i < current:
            stdscr.addstr(row, 2, "✓ ", DONE())
            stdscr.addstr(row, 4, step, DONE())
        elif i == current:
            stdscr.addstr(row, 2, "▸ ", HDR())
            stdscr.addstr(row, 4, step, HDR())
        else:
            stdscr.addstr(row, 4, step, NRM())

    divider = h - 7
    stdscr.addstr(divider, 2, "─" * (w - 4), HDR())
    for i, line in enumerate(log_lines[-5:]):
        r = divider + 1 + i
        if r < h - 1:
            stdscr.addstr(r, 2, line[:w - 4], NRM())
    stdscr.refresh()

def shell(cmd, log_lines, stdscr, steps, si, check=True):
    log_lines.append(f"$ {cmd[:68]}")
    draw_install(stdscr, steps, si, log_lines)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    for line in (r.stdout + r.stderr).strip().split("\n")[-2:]:
        if line.strip():
            log_lines.append(line[:68])
    draw_install(stdscr, steps, si, log_lines)
    if check and r.returncode != 0:
        with open(LOG_PATH, "a") as f:
            f.write(r.stderr)
    return r

def run_install(stdscr, cfg, dry_run=False):
    if dry_run:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "IRLOS — Dry Run")
        stdscr.addstr(2, 2, "DRY RUN — no system changes will be made.", DONE())
        stdscr.addstr(4, 2, "Config that would be applied:", LBL())
        dump = json.dumps(cfg, indent=2)
        for i, line in enumerate(dump.split("\n")[:h - 8]):
            stdscr.addstr(6 + i, 4, line[:w - 6], NRM())
        stdscr.addstr(h - 2, 2, "Press Enter to return to menu.", HDR())
        stdscr.refresh()
        stdscr.getch()
        return

    steps = INSTALL_STEPS
    log   = []
    si    = 0

    def tick():
        nonlocal si
        si += 1
        draw_install(stdscr, steps, si, log)

    draw_install(stdscr, steps, si, log)

    # 0 — hostname
    shell(f"hostnamectl set-hostname {cfg['hostname']}", log, stdscr, steps, si)
    with open("/etc/hostname", "w") as f: f.write(cfg["hostname"] + "\n")
    tick()

    # 1 — network
    if cfg["net_mode"] == "wifi" and cfg["wifi_ssid"]:
        shell(f'nmcli dev wifi connect "{cfg["wifi_ssid"]}" password "{cfg["wifi_pass"]}"',
              log, stdscr, steps, si, check=False)
    else:
        log.append("Ethernet — no WiFi config needed")
    draw_install(stdscr, steps, si, log)
    tick()

    # 2 — download NVIDIA .run
    ver      = cfg["nvidia_version"]
    run_path = f"/tmp/nvidia-{ver}.run"
    url      = f"https://us.download.nvidia.com/XFree86/Linux-x86_64/{ver}/NVIDIA-Linux-x86_64-{ver}.run"
    log.append(f"Downloading NVIDIA {ver}...")
    draw_install(stdscr, steps, si, log)
    shell(f"curl -L '{url}' -o '{run_path}'", log, stdscr, steps, si)
    shell(f"chmod +x '{run_path}'", log, stdscr, steps, si)
    tick()

    # 3 — install NVIDIA
    log.append("Running NVIDIA .run installer (silent)...")
    shell(f"'{run_path}' --silent --run-nvidia-xconfig", log, stdscr, steps, si)
    tick()

    # 4 — Xorg + Openbox
    shell("apt-get install -y xorg openbox xterm", log, stdscr, steps, si)
    tick()

    # 5 — OBS
    shell("add-apt-repository -y ppa:obsproject/obs-studio", log, stdscr, steps, si)
    shell("apt-get update -qq", log, stdscr, steps, si)
    shell("apt-get install -y obs-studio", log, stdscr, steps, si)
    tick()

    # 6 — noalbs
    log.append("Fetching latest noalbs release from GitHub...")
    draw_install(stdscr, steps, si, log)
    r = shell(
        "curl -s https://api.github.com/repos/nicehash/noalbs/releases/latest"
        " | grep browser_download_url | grep linux | head -1 | cut -d'\"' -f4",
        log, stdscr, steps, si, check=False
    )
    noalbs_url = r.stdout.strip()
    if noalbs_url:
        shell(f"curl -L '{noalbs_url}' -o /usr/local/bin/noalbs", log, stdscr, steps, si)
        shell("chmod +x /usr/local/bin/noalbs", log, stdscr, steps, si)
    else:
        log.append("WARNING: could not fetch noalbs URL — install manually later")
    tick()

    # 7 — x11vnc
    shell("apt-get install -y x11vnc", log, stdscr, steps, si)
    tick()

    # 8 — Xorg conf
    write_xorg_conf(cfg)
    log.append("Wrote /etc/X11/xorg.conf")
    draw_install(stdscr, steps, si, log)
    tick()

    # 9 — OBS scene + profile
    write_obs_scene(cfg)
    write_obs_profile(cfg)
    shell("chown -R irlos:irlos /home/irlos/.config", log, stdscr, steps, si)
    log.append("OBS scene + profile written")
    draw_install(stdscr, steps, si, log)
    tick()

    # 10 — noalbs config
    write_noalbs_config(cfg)
    log.append("noalbs config written")
    draw_install(stdscr, steps, si, log)
    tick()

    # 11 — SSH
    if cfg.get("ssh_pubkey"):
        os.makedirs("/home/irlos/.ssh", mode=0o700, exist_ok=True)
        with open("/home/irlos/.ssh/authorized_keys", "a") as f:
            f.write(cfg["ssh_pubkey"] + "\n")
        shell("chown -R irlos:irlos /home/irlos/.ssh", log, stdscr, steps, si)
        shell("chmod 600 /home/irlos/.ssh/authorized_keys", log, stdscr, steps, si)
        sshd = "/etc/ssh/sshd_config"
        shell(f"sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' {sshd}", log, stdscr, steps, si)
        shell(f"sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' {sshd}", log, stdscr, steps, si)
        log.append("SSH key installed, password auth disabled")
    else:
        log.append("No SSH key — password auth stays enabled")
    draw_install(stdscr, steps, si, log)
    tick()

    # 12 — VNC password
    os.makedirs("/home/irlos/.vnc", mode=0o700, exist_ok=True)
    shell(f"x11vnc -storepasswd '{cfg['vnc_pass']}' /home/irlos/.vnc/passwd", log, stdscr, steps, si)
    shell("chown -R irlos:irlos /home/irlos/.vnc", log, stdscr, steps, si)
    tick()

    # 13 — systemd
    write_systemd_units()
    shell("systemctl daemon-reload", log, stdscr, steps, si)
    shell("systemctl enable irlos-session.service irlos-vnc.service", log, stdscr, steps, si)
    tick()

    # 14 — Openbox autostart
    write_openbox_autostart()
    tick()

    # 15 — save config (strip secrets)
    os.makedirs("/etc/irlos", exist_ok=True)
    safe = {k: v for k, v in cfg.items() if k not in ("stream_key", "vnc_pass", "wifi_pass", "ssh_pubkey")}
    with open(CONFIG_PATH, "w") as f:
        json.dump(safe, f, indent=2)
    open(DONE_FLAG, "w").close()
    tick()

    # 16 — done
    h, w = stdscr.getmaxyx()
    stdscr.addstr(h - 2, 2, "Installation complete. Press Enter to reboot.", DONE())
    stdscr.refresh()
    stdscr.getch()
    subprocess.run("reboot", shell=True)

# ─── Welcome ──────────────────────────────────────────────────────────────────

def screen_welcome(stdscr):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    art = [
        "██╗██████╗ ██╗      ██████╗ ███████╗",
        "██║██╔══██╗██║     ██╔═══██╗██╔════╝",
        "██║██████╔╝██║     ██║   ██║███████╗",
        "██║██╔══██╗██║     ██║   ██║╚════██║",
        "██║██║  ██║███████╗╚██████╔╝███████║",
        "╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝",
    ]
    lines = [""] + art + [
        "",
        "IRL Stream Server OS  //  GPL-3.0",
        "",
        "Configure each item in the menu,",
        "then select Review & Install.",
        "On reboot, your stream will be live.",
        "",
        "Press Enter to begin.",
    ]
    start = max(0, (h - len(lines)) // 2)
    for i, line in enumerate(lines):
        row = start + i
        if row >= h:
            break
        col  = center_x(w, line)
        attr = HDR() if i in range(1, 7) else (LBL() if "GPL" in line else NRM())
        try:
            stdscr.addstr(row, col, line, attr)
        except curses.error:
            pass
    stdscr.refresh()
    stdscr.getch()

# ─── Screen router ────────────────────────────────────────────────────────────

SCREEN_MAP = {
    "hostname":      screen_hostname,
    "network":       screen_network,
    "nvidia":        screen_nvidia,
    "xorg":          screen_xorg,
    "obs":           screen_obs,
    "noalbs":        screen_noalbs,
    "vnc":           screen_vnc,
    "obs_config":    screen_obs_config,
    "noalbs_config": screen_noalbs_config,
    "ssh":           screen_ssh,
    "autostart":     screen_autostart,
}

# ─── Main loop ────────────────────────────────────────────────────────────────

def main(stdscr, dry_run=False):
    curses.curs_set(0)
    stdscr.keypad(True)
    init_colors()

    if os.path.exists(DONE_FLAG) and not dry_run:
        stdscr.addstr(0, 0, "Irlos already set up. Run 'streamctl config' to reconfigure.")
        stdscr.refresh()
        stdscr.getch()
        return

    screen_welcome(stdscr)

    cfg       = DEFAULT_CFG.copy()
    cursor    = 0
    completed = set()

    while True:
        draw_main_menu(stdscr, cfg, cursor, completed)
        ch = stdscr.getch()

        if ch == curses.KEY_UP:
            cursor = (cursor - 1) % len(MENU_ITEMS)
        elif ch == curses.KEY_DOWN:
            cursor = (cursor + 1) % len(MENU_ITEMS)
        elif ch in (10, 13):
            label, key = MENU_ITEMS[cursor]
            if key == "install":
                prompt = "Dry run — show config only, no changes." if dry_run else "Begin installation? This will modify the system."
                if confirm(stdscr, prompt):
                    run_install(stdscr, cfg, dry_run=dry_run)
                    if dry_run:
                        continue  # return to menu after dry run
                    return
            else:
                SCREEN_MAP[key](stdscr, cfg)
                completed.add(key)
        elif ch == ord('q'):
            if confirm(stdscr, "Quit installer?"):
                return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Irlos installer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the TUI without making any system changes")
    args = parser.parse_args()

    if not args.dry_run and os.geteuid() != 0:
        print("irlos-installer must run as root (or use --dry-run to test the UI).")
        sys.exit(1)

    os.makedirs("/var/log", exist_ok=True)
    curses.wrapper(main, args.dry_run)