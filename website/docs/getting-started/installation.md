---
sidebar_position: 2
title: "Installation"
description: "Install Hermes Agent on Linux, macOS, WSL2, native Windows, Android via Termux, or experimental FreeBSD CLI"
---

# Installation

Get Hermes Agent up and running in under two minutes!

:::tip Platform Support
For the full platform support matrix (which OSes, distribution methods, and
platform-gated features are supported), see **[Platform Support](./platform-support.md)**.
:::

## Quick Install
### With the Hermes Desktop installer on macOS or Windows (recommended)
To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it.

### Without Hermes Desktop:
For a command-line only install without Hermes Desktop, run:

FreeBSD users should follow the [native CLI instructions](#freebsd-native-cli-experimental) below instead of the quick-install URL.

#### Linux / macOS / WSL2 / Android (Termux)
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

#### Windows (native)

Run in powershell:
```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1) 
```

If you want to install & run Hermes Desktop after a command-line only install, simply run
```bash
hermes desktop
```

### What the Installer Does

The installer handles everything automatically — all dependencies (Python, Node.js, ripgrep, ffmpeg), the repo clone, virtual environment, global `hermes` command setup, and LLM provider configuration. By the end, you're ready to chat.

#### Install Layout

Where the installer puts things depends on whether you're installing as a normal user or as root:

| Installer                              | Code lives at                  | `hermes` binary                         | Data directory                       |
| -------------------------------------- | ------------------------------ | --------------------------------------- | ------------------------------------ |
| Per-user (git installer)               | `~/.hermes/hermes-agent/`      | `~/.local/bin/hermes` (symlink)         | `~/.hermes/`                         |
| Root-mode (`sudo curl … \| sudo bash`) | `/usr/local/lib/hermes-agent/` | `/usr/local/bin/hermes`                 | `/root/.hermes/` (or `$HERMES_HOME`) |

The root-mode **FHS layout** (`/usr/local/lib/…`, `/usr/local/bin/hermes`) matches where other system-wide developer tools land on Linux. It's useful for shared-machine deployments where one system install should serve every user. Per-user config (auth, skills, sessions) still lives under each user's `~/.hermes/` or explicit `HERMES_HOME`.

### After Installation

Reload your shell and start chatting:

```bash
source ~/.bashrc   # or: source ~/.zshrc
hermes             # Start chatting!
```

To reconfigure individual settings later, use the dedicated commands:

```bash
hermes model          # Choose your LLM provider and model
hermes tools          # Configure which tools are enabled
hermes gateway setup  # Set up messaging platforms
hermes config set     # Set individual config values
hermes config get     # Inspect individual config values
hermes setup          # Or run the full setup wizard to configure everything at once
```

:::tip Fastest path: Nous Portal
One subscription covers 300+ models plus the [Tool Gateway](/user-guide/features/tool-gateway) (web search, image generation, TTS, cloud browser). Skip the per-tool key juggling:

```bash
hermes setup --portal
```

That logs you in, sets Nous as your provider, and turns on the Tool Gateway in one command.
:::

:::tip Already running Hermes on another machine?
You don't need to rebuild your setup from scratch. Restore a full backup with `hermes import` (see [Exporting Hermes to another machine](/reference/faq#exporting-hermes-to-another-machine)), or bring over a single agent with `hermes profile import` (see [Moving a single profile to another machine](/reference/faq#moving-a-single-profile-to-another-machine)). Note that a profile export excludes credentials by design, so an export alone is not a full backup — [`hermes backup` vs `hermes profile export`](/reference/faq#hermes-backup-vs-hermes-profile-export) explains which to use.
:::

---

## Prerequisites

**Installer:** On non-Windows platforms, the only prerequisite is **Git**. On Linux, also make sure `curl` and `xz-utils` are available (the installer downloads Node.js as a `.tar.xz` archive). The desktop app additionally requires `g++` (or `build-essential` on Debian/Ubuntu) to compile native modules. The installer automatically handles everything else:

- **uv** (fast Python package manager)
- **Python 3.11** (via uv, no sudo needed)
- **Node.js v26** (for browser automation and WhatsApp bridge; existing system Node 22.22+, 24.11+, or 26+ is used as-is)
- **ripgrep** (fast file search)
- **ffmpeg** (audio format conversion for TTS)

:::info
You do **not** need to install Python, Node.js, ripgrep, or ffmpeg manually. The installer detects what's missing and installs it for you. Just make sure `git` is available (`git --version`). On Linux, ensure `curl` and `xz-utils` are installed (`sudo apt install curl xz-utils` on Debian/Ubuntu). For the desktop app, also install `build-essential` (`sudo apt install build-essential`).
:::

:::tip Nix users
Nix is **no longer an explicitly supported install path** (best-effort only). If you already use Nix (on NixOS, macOS, or Linux), there's a dedicated setup path with a Nix flake, declarative NixOS module, and optional container mode. See the **[Nix & NixOS Setup](./nix-setup.md)** guide.
:::

---

## FreeBSD native CLI (experimental)

This fork includes a native FreeBSD CLI installation path. It uses FreeBSD
packages and compiles Python extensions locally; it does not run Linux binaries
through the Linuxulator. The initial target is FreeBSD 15.1 amd64 with Python 3.12.
This is experimental support, not an upstream Tier 1 or Tier 2 commitment.

As an administrator, install the bootstrap tools:

```sh
pkg install -y bash curl git
```

Run the installer as the account that will use Hermes. Missing system packages
require root or working `sudo`; otherwise the installer prints the `pkg` command
for an administrator rather than falling back to foreign binaries. Native Rust
and image-library dependencies can take several minutes to install and compile.

Until this branch is merged, clone the fork first so the installer uses its
existing remote and branch. These commands are for a **new** installation; do not
clone over an existing checkout:

```sh
git clone --branch feat/freebsd-install \
  https://github.com/ajzrva-sys/hermes-agent.git "$HOME/.hermes/hermes-agent"
bash "$HOME/.hermes/hermes-agent/scripts/install.sh" \
  --dir "$HOME/.hermes/hermes-agent" --branch feat/freebsd-install --skip-setup
"$HOME/.local/bin/hermes" model
```

Use `bash scripts/install.sh`, not `/bin/bash`: packaged Bash lives under
`/usr/local/bin` on FreeBSD. Non-root installs use `~/.hermes/hermes-agent` and
`~/.local/bin`. Fresh root installs default to `/usr/local/lib/hermes-agent` and
`/usr/local/bin`; existing installs under `$HERMES_HOME/hermes-agent` stay in place.
An explicit `--dir`, including the example above, preserves the chosen checkout
and uses the per-user launcher. Configuration and sessions remain in
`$HERMES_HOME` (default `~/.hermes`). Add `~/.local/bin` to `PATH` when using the
per-user layout.
When using a custom data location, also set `HERMES_HOME` to that location when
launching Hermes; the launcher does not permanently bind itself to one profile.

### Other users of a root installation

With the shared layout, ordinary users run `/usr/local/bin/hermes` directly;
they do not need another copy of the application or access to root's home.
On first use, Hermes initializes their own `~/.hermes` (or explicit
`HERMES_HOME`) and copies the bundled skill library, including its supporting
files. FreeBSD-compatible skills are available without a manual sync step.

Run these as the account that will use Hermes:

```sh
hermes skills list
hermes model
```

Each account configures its own provider credentials. Root's configuration,
credentials, memories, and sessions are not copied. An unreadable legacy `.env`
in the shared installation is skipped; do not make it world-readable to work
around startup. Existing user skills, deletions, and bundled-skill opt-outs are
preserved. Updating the shared program and its dependencies remains an
administrator operation; optional integrations still need their own setup.

### Native dependencies and updates

- Python comes from `python312`, with `py312-sqlite3` installed separately.
  Without that split package, even CLI startup fails importing `_sqlite3`.
- Hermes uses native `uv` from `pkg`. Its private uv lookup resolves that binary;
  neither the installer nor updater replaces it using Astral's binary downloads.
  Upgrade the system Python, uv, and SQLite packages through FreeBSD's package manager.
- Node.js/npm are reused from supported native packages, or provisioned with
  `pkg install node24 npm-node24`. A missing optional Node toolchain does not
  block the CLI. `bash scripts/install.sh --ensure node` explicitly checks/provisions it.
- The dependency metadata restricts `pillow-heif` to the version range compatible
  with packaged libheif 1.22. Other platforms retain their existing wheel-backed
  dependency range. The same markers apply during installation and dependency repair.
- The reviewed `uv.lock` is used for installation. Native source builds replace
  unavailable FreeBSD wheels; do not substitute packages with `--no-deps`.
- For this fork branch, update with `hermes update --branch feat/freebsd-install`.
  Keep system packages current and run `hermes doctor` afterward. A vulnerable
  system SQLite build requires a package update, not a managed-Python download.

Verify the installed environment:

```sh
hermes --version
hermes doctor
uv pip check --python "$HOME/.hermes/hermes-agent/venv/bin/python"
```

The automated path remains CLI-first: Computer Use, Node UI dependencies, and
automatic gateway service setup are skipped. Desktop installation is rejected.
Provider authentication is separate; run `hermes model` before requesting a model response.

### Jail isolation (experimental)

On FreeBSD 15.1 Hermes can run its tool workloads inside native jails managed by
the shared `codex_freebsd_sandbox` service (the same service used by Codex and
CA). An administrator installs and starts that service and allowlists the
invoking UID; Hermes itself needs no root and creates no second daemon.

Build the unprivileged bridge once per checkout, as the installing user:

```sh
cd "$HERMES_HOME/hermes-agent/native/freebsd-sandbox" && cargo build --release --locked
```

Then enable it for a profile with `hermes setup` (Terminal backend → FreeBSD
jail) or directly in `$HERMES_HOME/config.yaml`:

```yaml
terminal:
  backend: freebsd_jail
  cwd: /path/to/project
  freebsd_jail:
    grants: []            # extra concrete read/write/deny paths
    read_only: false
    network: restricted   # "enabled" only for jobs that must reach the network
```

`hermes doctor` reports the service identity, protocol capabilities, and the
effective workspace policy; setup and the web dashboard expose the same backend.

**Covered by the jail:** terminal commands, background jobs and PTYs, file
reads, searches, edits and patches, document parsing, `execute_code` kernels,
stdio MCP and LSP servers, shell hooks, and cron scripts.

**Not jailed:** provider and messaging connections, browser/desktop automation,
in-process plugin code, and the downloads the gateway performs for inbound
attachments. Selection is fail-closed: an unavailable service, an unsupported
policy, or a setup error blocks tool execution instead of falling back to host
execution.

Security boundary:

- Jobs run as the invoking user with no-new-privileges; controller `sudo`
  material is never passed into a jail and SUID binaries cannot elevate.
- The selected project is the default grant. `/`, the home directory, and the
  Hermes profile are never granted implicitly; `~/.hermes`, `~/.ssh`, `~/.codex`,
  `~/.config/ca`, cloud credential directories, and other private state stay
  denied even when a containing directory is granted.
- Worker environments come from an explicit runtime allowlist; provider
  credentials, tokens, and sockets stay with the controller.
- Worker networking is disabled by default (`network: restricted`).
- Cron scripts live under the profile, which stays denied to workers: the
  scheduler hands the jail a private staging copy and runs the job in the
  workspace unless the job configures a `workdir`.

Troubleshooting and rollback:

- "FreeBSD jail service unavailable" in `hermes doctor` means the administrator
  must start `codex_freebsd_sandbox` or fix its socket/UID allowlist; a missing
  bridge binary reports its path in the same message.
- A job that needs files outside the project fails closed; add a concrete grant
  (`terminal.freebsd_jail.grants`) rather than a parent directory.
- To roll back, set `terminal.backend` back to `local` (or re-run `hermes setup`)
  and restart the profile. The jail service, the installed tree, and other
  profiles are unaffected; draining running jobs first avoids killing them
  mid-flight.

### Developer checkout and authentication

For an existing checkout, `bash setup-hermes.sh --skip-setup` reuses the native
installer stages, including package checks and dependency policy. It deliberately
does not fetch, switch branches, or stash a developer's working tree.

If a `claude setup-token` executable has the wrong binary format (for example a
Linux binary on native FreeBSD), setup returns to manual authentication rather
than crashing. Run `claude setup-token` on a supported machine and enter its
result in the authentication prompt, or choose an API-key provider with `hermes model`.

### Optional system browser

Playwright does not publish a FreeBSD Chromium build. Following the system-browser
approach in [macosxgeek's PR #33487](https://github.com/NousResearch/hermes-agent/pull/33487):

```sh
# As an administrator:
pkg install chromium
# In the account/session running Hermes:
export AGENT_BROWSER_EXECUTABLE_PATH=/usr/local/bin/chromium
```

`bash scripts/install.sh --ensure browser` prints this manual setup guidance;
it does not download a foreign browser or claim browser automation is ready.
Verify the selected browser/backend separately. Desktop/TUI and wheel-only voice
engines are still outside the tested native installation path. A headless FreeBSD
dashboard does not launch a terminal browser; graphical sessions retain auto-open.

### Optional rc.d gateway supervision

First configure a gateway platform and verify `hermes gateway run` under the
account that will own it. The built-in service installer is not an rc.d manager.
For manual supervision, save this example as `/usr/local/etc/rc.d/hermes`:

```sh
#!/bin/sh
# PROVIDE: hermes
# REQUIRE: NETWORKING
# KEYWORD: shutdown
. /etc/rc.subr
name="hermes"
rcvar="hermes_enable"
command="/usr/sbin/daemon"
start_cmd="hermes_start"
hermes_start() {
    /usr/sbin/daemon -f -R 5 -P "$pidfile" -o "$hermes_log" \
        -u "$hermes_user" /usr/bin/env \
        "PATH=/usr/local/bin:/usr/bin:/bin" "HERMES_HOME=$hermes_home" \
        "$hermes_command" gateway run
}
load_rc_config "$name"
: "${hermes_enable:=NO}"
: "${hermes_user:=hermes}"
: "${hermes_home:=/home/hermes/.hermes}"
: "${hermes_command:=/usr/local/bin/hermes}"
: "${hermes_log:=/var/log/hermes-gateway.log}"
: "${hermes_pidfile:=/var/run/hermes.pid}"
pidfile="$hermes_pidfile"
run_rc_command "$1"
```

Set `hermes_user` to an existing account and `hermes_home`/`hermes_command` to its
configured data directory and executable launcher in `/etc/rc.conf`. Ensure that
account can traverse the install path. Then, as root:

```sh
chmod 755 /usr/local/etc/rc.d/hermes
sysrc hermes_enable=YES
service hermes start
service hermes status
# To stop, signal the supervisor rather than a child that would be restarted:
service hermes stop
```

This adapts the upstream PR's manual recipe to `daemon -P` and foreground
`gateway run`, rather than nesting `gateway start` inside another supervisor.
Manage restarts with `service hermes restart`; fleet-wide rc.d management by
`hermes update` is not provided. No service is enabled by the installer.

If the terminal reports missing color capabilities, use `TERM=xterm-256color`
with a terminal that supports it.

The platform helper, authentication fallback, headless-dashboard behavior,
native Node/system-browser approach, root layout and manual service guidance are
adapted from macosxgeek's PR #33487, preserving the newer dependency/update safeguards.

---

## Manual / Developer Installation

If you want to clone the repo and install from source — for contributing, running from a specific branch, or having full control over the virtual environment — see the [Development Setup](../developer-guide/contributing.md#development-setup) section in the Contributing guide.

---

## Non-Sudo / System Service User Installs

Running Hermes as a dedicated unprivileged user (e.g. a `hermes` systemd service account, or any user without `sudo` access) is supported. The only thing on the install path that genuinely needs root is Playwright's `--with-deps` step, which `apt`-installs shared libraries (`libnss3`, `libxkbcommon`, etc.) used by Chromium. The installer detects whether sudo is available and gracefully degrades when it isn't — it will install the Chromium binary into the service user's own Playwright cache and print the exact command an administrator needs to run separately.

**Recommended split (Debian/Ubuntu):**

1. **One time, as an admin user with sudo**, install the system libraries Chromium needs:
   ```bash
   sudo npx playwright install-deps chromium
   ```
   (You can run this from anywhere — `npx` will fetch Playwright on the fly.)

2. **As the unprivileged service user**, run the regular installer. It will detect the missing sudo, skip `--with-deps`, and install Chromium into the user's local Playwright cache:
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   ```

   If you want to skip the Playwright step entirely — for example because you're running headless and don't need browser automation — pass `--skip-browser`:
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-browser
   ```

   The installer also pre-installs [`cua-driver`](../user-guide/features/computer-use.md) so the Computer Use toolset works the moment you enable it; pass `--skip-computer-use` to opt out (it will then install on demand when you enable the tool).

3. **Make `hermes` available to the service user's shells.** The installer writes the launcher to `~/.local/bin/hermes`. System service accounts often have a minimal PATH that doesn't include `~/.local/bin`. Either add it to the user's environment, or symlink the launcher into a system location:
   ```bash
   # Option A — add to the service user's profile
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

   # Option B — symlink system-wide (run as an admin)
   sudo ln -s /home/hermes/.hermes/hermes-agent/venv/bin/hermes /usr/local/bin/hermes
   ```

4. **Verify:** `hermes doctor` should now run cleanly. If you get `ModuleNotFoundError: No module named 'dotenv'`, you're invoking the repo source `hermes` file (`~/.hermes/hermes-agent/hermes`) with system Python instead of the venv launcher (`~/.hermes/hermes-agent/venv/bin/hermes`) — fix step 3.

5. **Running the messaging gateway from this account?** A user-level service stops at logout and does not start at boot until you enable lingering for the service user:

   ```bash
   sudo loginctl enable-linger <service-user>
   ```

   See [Messaging Gateway](/user-guide/messaging/) for the service setup itself.

The same pattern works on Arch (the installer uses pacman with the same sudo-detection logic), Fedora/RHEL, and openSUSE — those distros don't support `--with-deps` at all, so an administrator always installs the system libraries separately. The relevant `dnf`/`zypper` commands are printed by the installer.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `hermes: command not found` | Reload your shell (`source ~/.bashrc`) or check PATH |
| `API key not set` | Run `hermes model` to configure your provider, or `hermes config set OPENROUTER_API_KEY your_key` |
| Missing config after update | Run `hermes config check` then `hermes config migrate` |

For more diagnostics, run `hermes doctor` — it will tell you exactly what's missing and how to fix it.

### Symlinked home directories and external storage

Hermes supports a symlinked `HERMES_HOME` and symlinked home subdirectories,
including `hooks`, `skills`, `sessions`, and `logs`. During home initialization,
existing directory links are preserved, and permissions on linked directories
(and descendants such as `logs/curator`) are left to their owner.

If a link target is missing, inaccessible, or not a directory, initialization
stops with a storage error naming the path and link target. Hermes does **not**
replace the link or create its missing target: doing so could write data onto
the local disk while an external or NAS volume is unmounted. Check the reported
link, restore the mount or correct its target, and verify access permissions
before retrying. For a deliberately new dotfiles target, create it yourself only
after confirming the intended storage is available.

`hermes doctor` reports these failures as storage problems, not invalid YAML.
Keep your existing `config.yaml`; running `hermes setup` is not the repair for an
unavailable directory. This is a directory-availability check, not a mount monitor:
an existing directory cannot establish that the intended volume is mounted.

## Install method auto-detection

Hermes auto-detects whether it was installed via the git installer, Docker, or NixOS, and `hermes update` prints the matching update command for that path. There's no env var to set — the detection is based on the install layout (`~/.hermes/hermes-agent/` checkout, Docker image stamp, or Nix store path). `hermes doctor` also surfaces the detected method under its environment summary.
