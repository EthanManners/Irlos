**IRLOS**

IRL Stream Server OS

Technical Documentation & Product Roadmap // GPL-3.0

# **Overview**

Irlos is a purpose-built, GPL-licensed Linux distribution for IRL streamers. It turns any x86_64 machine with an NVIDIA GPU into a plug-and-play IRL stream server. Flash a USB, boot the machine, run a five-question setup wizard, reboot - your stream is live.

The entire software stack is pre-installed and pre-configured. The user never touches a config file. Stream key, platform, and WiFi credentials are the only inputs required. Everything else - OBS, SRT ingest, bitrate-based scene switching, VNC access - is wired up and running automatically on boot.

Irlos is built on the Red Hat model: the OS is free and open source forever, revenue comes from managed cloud hosting, a web dashboard, physical USB products, and support tiers.

# **Design philosophy**

Irlos is a single-purpose appliance, not a general-purpose Linux distribution. It is inspired by the mentality of old-school specialized machines - Avid editing systems, Cisco routers, broadcast hardware - that do one thing with zero compromise.

- No Ubuntu branding anywhere in the boot sequence, shell, or UI
- SSH drops you into a full-screen CUI dashboard, not a bash prompt
- OBS is forked into IrlosStudio - stripped down, stream key backend-only
- Every service is managed by systemd and starts automatically on boot
- The dummy plug is a first-class hardware requirement, not a workaround
- GPL licensed - the community owns it, you can't close it

# **System architecture**

## **Signal flow**

The complete path from phone to platform:

Phone/encoder → SRT/RTMP → SLS (port 9000) → OBS media source

OBS → NVENC encode → RTMP → Kick / Twitch / YouTube

SLS (SRT Live Server) runs as a systemd service, receives the incoming SRT feed, and exposes it locally. OBS reads from localhost via a pre-configured ffmpeg media source. noalbs monitors the OBS websocket and switches scenes automatically based on bitrate thresholds.

## **Display layer**

Xorg runs against the HDMI dummy plug with a pre-written xorg.conf that tells the NVIDIA driver to initialize against the dummy display. Openbox is the window manager - minimal, zero overhead. OBS opens maximized inside the Openbox session. x11vnc reads the X framebuffer and serves it on localhost:5901. VNC is never exposed to the internet - access is via SSH tunnel only, or via the noVNC web interface over HTTPS.

## **Remote access layers**

Two access methods with different trust levels:

- SSH - terminal access, CUI dashboard, config management, streamctl CLI
- VNC - full visual access to IrlosStudio via SSH tunnel or noVNC browser interface

Stream keys are stored in /etc/irlos/config.json and are never visible in the VNC/OBS interface. A user with VNC access can control scenes and visuals but cannot extract credentials.

## **File system layout**

/home/irlos/.config/obs-studio/ OBS profile, scenes, global config

/home/irlos/.config/noalbs/ noalbs config.json

/home/irlos/.config/openbox/ autostart script

/home/irlos/.vnc/passwd VNC password file

/home/irlos/.ssh/authorized_keys SSH public keys

/etc/irlos/config.json Stream key, platform, runtime config

/etc/X11/xorg.conf NVIDIA + dummy plug display config

/etc/systemd/system/ irlos-session + irlos-vnc units

/usr/local/bin/streamctl CLI control tool

/usr/local/lib/irlos/ Installer and core scripts

/usr/local/bin/sls SRT Live Server binary (static)

# **Components**

## **SLS - SRT Live Server**

SLS is compiled statically from source inside the Irlos build environment (Ubuntu 22.04 Jammy chroot) and shipped as a pre-built binary in the ISO. Static compilation means zero runtime library dependencies - the binary runs identically on every machine that boots Irlos.

SLS was chosen over mediamtx for its production stability under sustained IRL streaming loads. The complex compile process is solved once at build time and never exposed to the end user.

Default configuration: SRT input on port 9000, stream ID passthrough, local relay to OBS media source.

## **OBS / IrlosStudio**

Phase 1 ships standard OBS Studio pre-configured with the Irlos scene collection and NVENC output profile. Phase 3 introduces IrlosStudio - a fork of OBS with the following changes:

- Stream key removed from the UI entirely - read from /etc/irlos/config.json at launch
- Unnecessary source types removed - only ffmpeg media source, browser source, and text retained
- Recording UI removed - Irlos is a streaming appliance, not a recorder
- Settings panels stripped to essentials - output, audio, hotkeys
- IrlosStudio branding throughout

IrlosStudio remains GPL-compliant as OBS is GPL-2.0.

## **noalbs**

noalbs monitors the OBS websocket on localhost:4455 and switches scenes automatically based on incoming bitrate. Pre-configured thresholds:

- Normal scene (Live): bitrate above low threshold
- Low scene (BRB): bitrate below low threshold
- Offline scene: bitrate below offline threshold

Default thresholds are 2000 kbps (low) and 500 kbps (offline). These are configurable via the first-boot wizard and the streamctl config command.

## **streamctl**

streamctl is the primary CLI interface for Irlos. All stream management is done through this tool.

streamctl start Start OBS and noalbs

streamctl stop Stop both

streamctl status Show running status and stream health

streamctl vnc Launch VNC - prints SSH tunnel instructions

streamctl config Re-run the configuration wizard

streamctl update Pull latest configs from upstream

## **SSH CUI dashboard**

When a user SSH's into an Irlos machine, instead of a bash prompt they are dropped into a full-screen curses dashboard. The dashboard shows:

- Stream status - live / offline / error
- Current scene and bitrate
- Uptime and system health
- Quick controls - start, stop, restart, switch scene
- Live log tail
- VNC launch shortcut

Escape or a dedicated keybind drops to a real bash shell for admin work.

## **noVNC web interface**

websockify bridges the x11vnc session to a WebSocket. noVNC serves a full browser-based VNC client over HTTPS via nginx. The user opens a URL, authenticates, and sees the full IrlosStudio interface in their browser with no VNC client required.

In the managed cloud tier, each customer gets a subdomain (stream1.irlos.io) routed to their specific server instance via nginx reverse proxy.

## **Calamares installer**

The bootable ISO ships with Calamares - the same graphical installer used by Manjaro and EndeavourOS. Calamares handles disk partitioning, bootloader installation, and user creation. An Irlos-branded slide show runs during installation. On first boot after installation, the Irlos first-boot wizard launches automatically.

## **First-boot wizard**

A lightweight curses wizard that runs exactly once after Calamares installation. Collects five inputs:

- Stream key
- Platform (Kick / Twitch / YouTube / Custom RTMP)
- WiFi credentials (optional - skip for wired)
- SSH public key (optional - disables password auth if provided)
- VNC password

The wizard patches /etc/irlos/config.json, the OBS profile, and the noalbs config, then reboots. On reboot, the stream server is fully operational.

# **Development roadmap**

| **Phase** | **Description**                                                                                                               | **Timeline**   | **Deliverable**       |
| --------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------- | --------------------- |
| Phase 1   | Core OS build in chroot - SLS compile, all configs pre-baked, SSH CUI dashboard, streamctl, first-boot wizard, Irlos branding | 2-3 weeks      | Bootable chroot image |
| Phase 2   | Bootable ISO - Calamares integration, squashfs build pipeline, GRUB EFI+legacy, end-to-end hardware test                      | 1 week         | irlos-1.0.iso         |
| Phase 3   | IrlosStudio - OBS fork, strip unnecessary features, backend stream key, rebrand                                               | 3-4 weeks      | IrlosStudio binary    |
| Phase 4   | Cloud layer - noVNC + websockify, nginx reverse proxy, subdomain routing, GPUmart one-click deploy, dashboard MVP             | 3-4 weeks      | irlos.io dashboard    |
| Phase 5   | Product - USB packaging, branded dummy plug, GPUmart partnership, public launch                                               | Parallel w/ P4 | Shipped product       |

## **Phase 1 - Core OS detail**

- Compile SLS statically in Ubuntu 22.04 chroot
- Pre-bake SLS config - port 9000, stream ID passthrough
- Pre-bake OBS scene collection - Live, BRB, Offline scenes with SLS media source
- Pre-bake OBS profile - NVENC encoder, 1080p60, bitrate placeholder
- Pre-bake noalbs config - OBS websocket localhost:4455, default thresholds
- Write xorg.conf for NVIDIA + dummy plug
- Write systemd units - irlos-session, irlos-vnc
- Write Openbox autostart - OBS + noalbs launch
- Write streamctl CLI
- Write SSH CUI dashboard
- Write first-boot wizard
- Custom GRUB splash, MOTD, os-release - no Ubuntu branding

## **Phase 2 - ISO build detail**

- Set up Calamares with Irlos branding and YAML module config
- Wire first-boot wizard as Calamares post-install hook
- mksquashfs the chroot filesystem
- Build bootable ISO with GRUB supporting EFI and legacy BIOS
- Flash to USB - test on physical hardware
- Full end-to-end test: phone SRT → SLS → OBS → Kick
- Validate VNC over SSH tunnel

# **Product tiers**

## **Self-hosted USB (~\$60-80 one time)**

Pre-flashed USB stick with the Irlos ISO. Branded matte black packaging. Includes a branded HDMI dummy plug. Small card with SSH instructions and irlos.io. Flash to any x86_64 machine with an NVIDIA GPU and boot. The ISO is also available as a free download - the USB is convenience and branding.

## **Irlos Cloud - base tier (~\$30-50/month)**

GPUmart GPU server (GTX 1650) with Irlos pre-installed and a dummy plug already connected. Customer receives SSH credentials by email. SSH in, get the CUI dashboard, enter stream key and platform, streaming in under five minutes. No VNC, no GUI, no terminal experience required beyond SSH.

## **Irlos Cloud - OBS tier (+\$X/month)**

Same server with VNC unlocked. Full IrlosStudio access in the browser via noVNC over HTTPS. For streamers who need to manage scenes, overlays, and alerts visually. Stream key remains backend-only and is never exposed in the UI.

## **Enterprise / team (custom pricing)**

Multi-server setups for production streamers, media companies, and IRL content studios. Custom SLA, dedicated support, white-label options.

# **Business model**

Irlos follows the Red Hat model: the OS is GPL-licensed and free forever. Nobody can take the code, close it, and sell it as a proprietary product. Revenue comes entirely from the services, hardware, and infrastructure built around the open core.

## **Revenue streams**

- USB physical product - high margin, low COGS (~\$8), ships worldwide
- Cloud dashboard subscription - recurring, scales with user count
- GPUmart referral commission - passive, every cloud customer is a GPUmart customer
- Managed hosting margin - buy at GPUmart wholesale, sell at Irlos Cloud retail
- Support tiers - priority support, onboarding, custom configurations

## **GPUmart partnership**

GPUmart (DatabaseMart) are among the only cloud providers offering low-end consumer NVIDIA GPUs (GTX 1650, RTX 3060) at accessible price points (~\$30-80/month). This is the exact hardware Irlos requires for NVENC encoding. Enterprise GPU cloud providers (AWS, GCP, CoreWeave) sell A100s and H100s at \$2-3/hour - entirely wrong for IRL streaming.

The partnership model: GPUmart adds Irlos as an OS option in their deploy interface alongside Ubuntu and Windows Server. They ship servers with dummy plugs pre-installed for Irlos orders. Irlos.io markets GPUmart as the officially supported cloud provider. Commission on every referral conversion.

From GPUmart's perspective: zero engineering risk, new customer vertical (IRL streamers - not their typical buyer), incremental hardware revenue from existing inventory. An afternoon of integration work for a new distribution channel.

# **Security model**

## **Credential isolation**

- Stream key stored in /etc/irlos/config.json - never exposed in OBS/VNC UI
- VNC bound to localhost:5901 - never exposed to internet
- SSH key-only authentication when pubkey is provided at setup
- Root login disabled in sshd_config
- VNC access via SSH tunnel or authenticated noVNC HTTPS only

## **Access levels**

- SSH - full system access, CUI dashboard, config management, streamctl
- VNC - visual OBS control only, no credential access
- noVNC web - same as VNC, authenticated via nginx HTTP auth or token

# **Build environment**

The Irlos ISO is built from a debootstrap Ubuntu 22.04 Jammy chroot on an Arch Linux host. All packages are installed inside the chroot, ensuring the resulting system is native Jammy regardless of the build host.

## **Chroot setup**

debootstrap jammy /home/ethan/Irlos <http://archive.ubuntu.com/ubuntu>

mount --bind /dev /home/ethan/Irlos/dev

mount --bind /dev/pts /home/ethan/Irlos/dev/pts

mount -t proc proc /home/ethan/Irlos/proc

mount -t sysfs sysfs /home/ethan/Irlos/sys

chroot /home/ethan/Irlos /bin/bash

## **SLS compile flags**

SLS is compiled with static linking inside the chroot. The resulting binary has zero runtime dependencies and runs identically on any x86_64 machine booting Irlos.

apt install cmake gcc g++ libssl-dev libsrt-dev make git

git clone <https://github.com/Edward-Wu/srt-live-server>

cd srt-live-server && mkdir build && cd build

cmake -DCMAKE_BUILD_TYPE=Release ..

make -j\$(nproc)

cp bin/sls /usr/local/bin/sls

Irlos - GPL-3.0 - github.com/irlos // irlos.io
