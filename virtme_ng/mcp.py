# -*- mode: python -*-
# Copyright 2025 Andrea Righi <arighi@nvidia.com>

"""
MCP Server for virtme-ng - Kernel development and testing tools
Provides tools for AI agents to configure and test Linux kernels

IMPORTANT NOTES FOR AI AGENTS:
================================

1. BUILDING KERNELS - CRITICAL INSTRUCTIONS
   ==========================================

   ⚠️  NEVER use the run_kernel tool to build kernels!
   ⚠️  ALWAYS use shell commands with 'vng -v --build' for building!

   When a user asks to test a kernel that hasn't been built yet, use
   'vng -v --build' instead of running 'make' directly. This is faster,
   more reliable, and handles configuration automatically.

   LOCAL BUILDS:
   -------------
   Use: vng -v --build

   REMOTE BUILDS (when user specifies a build server/host):
   --------------------------------------------------------
   Use: vng -v --build --build-host <hostname>

   ANY of these user requests indicate a REMOTE BUILD:
   • "build on my server"
   • "compile on <hostname>"
   • "use my build machine"
   • "build this remotely"
   • "use the build server called <name>"

   ⏱️  BUILD TIMEOUT REQUIREMENTS - CRITICAL:
   ─────────────────────────────────────────
   Kernel builds can take a LONG time (10-60+ minutes depending on the system).

   ⚠️  ALWAYS use a timeout of AT LEAST 900-1200 seconds (15-20 minutes)
   ⚠️  For full builds or slower systems, use 3600 seconds (1 hour) or more

   Default shell command timeouts (30 seconds) are TOO SHORT and WILL FAIL!

   Example with proper timeout:
     Shell(command="vng -v --build", timeout=1200000)  # 20 minutes in milliseconds

   Why use vng -v --build:
   - Automatically generates minimal .config if missing (saves time)
   - Optimized for quick builds (compiles only what's needed for testing)
   - Builds typically complete in minutes instead of hours
   - Supports remote build hosts for cross-compilation
   - Handles all build dependencies and options correctly

   Basic build command (with proper timeout):
     Shell(command="vng -v --build", timeout=1200000)

   Build specific commit/tag:
     Shell(command="vng -v --build --commit v6.2-rc4", timeout=1200000)

   Build with custom config items:
     Shell(command="vng -v --build --configitem CONFIG_KASAN=y --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

   Build on remote host "builder" (for cross-compilation or distributed builds):
     Shell(command="vng -v --build --build-host builder", timeout=1200000)

   Build with environment variables (e.g., Rust support):
     Shell(command="vng -v --build RUSTC=rustc-1.62 BINDGEN=bindgen-0.56", timeout=1200000)

   Build for different architecture:
     Shell(command="vng -v --build --arch arm64 --root /opt/chroot/arm64/", timeout=1200000)

   ⚠️  CRITICAL TIMEOUT WARNING:
   ────────────────────────────
   vng -v --build can take 10-60+ minutes to complete!

   When using Shell tool, ALWAYS specify timeout in MILLISECONDS:
   • Minimum: 900000ms (15 minutes)
   • Recommended: 1200000ms (20 minutes)
   • Safe for all builds: 3600000ms (1 hour)

   DO NOT use default 30-second timeout - builds WILL fail!

   ═══════════════════════════════════════════════════════════════════
   REMOTE BUILD HOST (--build-host) - CRITICAL FOR REMOTE BUILDS
   ═══════════════════════════════════════════════════════════════════

   When the user asks to build on a remote host, remote server, build server,
   or specifies ANY hostname for building, ALWAYS use --build-host option.

   🔴 MANDATORY USAGE: When user mentions ANY of these:
   ────────────────────────────────────────────────────
   ✓ "build on my server"
   ✓ "build on <hostname>"
   ✓ "compile on remote host"
   ✓ "use my build server"
   ✓ "build remotely"
   ✓ "compile this on <machine-name>"
   ✓ "use the build machine"

   → ALWAYS use: vng -v --build --build-host <hostname>

   Command format (MANDATORY for remote builds):
   ──────────────────────────────────────────────
     vng -v --build --build-host <hostname>

   How it works:
   - The source is pushed to ~/.virtme on the remote host via SSH
   - The build happens on the remote host
   - Only required files (bzImage, modules, etc.) are copied back after build
   - Useful for cross-compilation or using powerful build servers

   Examples (all with proper 20-minute timeouts):
     Shell(command="vng -v --build --build-host myserver", timeout=1200000)
     Shell(command="vng -v --build --build-host builder", timeout=1200000)
     Shell(command="vng -v --build --build-host build01.example.com", timeout=1200000)
     Shell(command="vng -v --build --build-host builder --arch arm64", timeout=1200000)
     Shell(command="vng -v --build --build-host myserver --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

   ⏱️  ALWAYS use timeout=1200000 (20 min) or higher for ALL builds!

2. EACH run_kernel INVOCATION SPAWNS A NEW, INDEPENDENT VM
   ===========================================================

   ⚠️  CRITICAL: Every call to run_kernel() creates a FRESH, ISOLATED VM instance!

   This means:
   ✗ State does NOT persist between run_kernel invocations
   ✗ You CANNOT run a command and then check dmesg in a separate invocation
   ✗ You CANNOT set up something in one call and use it in another
   ✗ Each VM starts fresh with no memory of previous invocations

   ✓ CORRECT: Combine commands in a SINGLE run_kernel invocation:
     run_kernel({"command": "some_command && dmesg | grep -i warning"})
     run_kernel({"command": "modprobe mymod && cat /sys/module/mymod/parameters/debug"})
     run_kernel({"command": "cd /tmp && echo test > file && cat file"})

   ✗ WRONG: Multiple separate invocations (these are INDEPENDENT VMs!):
     run_kernel({"command": "some_command"})        # VM instance #1
     run_kernel({"command": "dmesg"})               # VM instance #2 (different VM!)
     # These two commands run in COMPLETELY DIFFERENT virtual machines!
     # The dmesg output will NOT contain anything from the first command!

   WHY THIS MATTERS:
   - run_kernel() starts a QEMU VM, runs the command, captures output, then EXITS
   - Each invocation = fresh boot, fresh memory, fresh state
   - Like rebooting a computer between each command

   EXAMPLES:

   ❌ BAD - Won't work (separate VMs):
      run_kernel({"command": "insmod mymodule.ko"})
      run_kernel({"command": "dmesg | grep mymodule"})  # Won't see module from first call!

   ✅ GOOD - Works (single VM):
      run_kernel({"command": "insmod mymodule.ko && dmesg | grep mymodule"})

   ❌ BAD - Won't work (separate VMs):
      run_kernel({"command": "echo 1 > /proc/sys/kernel/printk"})
      run_kernel({"command": "cat /proc/sys/kernel/printk"})  # Will show default, not 1!

   ✅ GOOD - Works (single VM):
      run_kernel({"command": "echo 1 > /proc/sys/kernel/printk && cat /proc/sys/kernel/printk"})

   SHELL OPERATORS for combining commands:
   - && : Run second command only if first succeeds
   - ;  : Run commands sequentially regardless of success
   - || : Run second command only if first fails

   Example with complex script:
     run_kernel({"command": "cd /path && ./test.sh && dmesg | tail -50"})

3. PTS (Pseudo-Terminal) Requirement
   -----------------------------------
   virtme-ng (vng) requires a valid pseudo-terminal (PTS) to run. In automated
   environments without a real terminal, vng commands will fail with:
     "ERROR: not a valid pts, try to run vng with a valid PTS (e.g., inside tmux or screen)"

   This MCP server's run_kernel tool automatically handles PTS requirements.

   For direct shell commands, use 'script' to provide a PTS:
     script -q -c "vng -- command" /dev/null 2>&1

   The 'script' command:
     -q: Quiet mode (no script start/stop messages)
     -c: Execute command and exit
     /dev/null: Discard the typescript file (we only need stdout/stderr)

4. Typical Workflow for Testing Kernel Changes
   ============================================

   STEP 1: BUILD (use shell command, NOT run_kernel tool!)
   ────────────────────────────────────────────────────────

   ⏱️  TIMEOUT REQUIREMENT: Builds take 10-60+ minutes!
       Always use timeout of at LEAST 1200000ms (20 min) in Shell tool

   a) Local build:
      Shell(command="vng -v --build", timeout=1200000)
      (NEVER use: make -j$(nproc), ALWAYS use: vng -v --build)

   b) Remote build (when user specifies a hostname/server):
      Shell(command="vng -v --build --build-host <hostname>", timeout=1200000)

   c) Build with custom config:
      Shell(command="vng -v --build --configitem CONFIG_KASAN=y", timeout=1200000)

   d) Remote build with custom config:
      Shell(command="vng -v --build --build-host builder --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

   STEP 2: TEST (use run_kernel tool or shell command)
   ────────────────────────────────────────────────────

   After building, test the kernel:
   • Use run_kernel tool, OR
   • Use shell command: script -q -c "vng -- uname -r" /dev/null 2>&1

   ═══════════════════════════════════════════════════════════════════
   COMPLETE WORKFLOW EXAMPLES (with proper timeouts!):
   ═══════════════════════════════════════════════════════════════════

     Example 1: Local build + test with KASAN
     ─────────────────────────────────────────
     # STEP 1: BUILD (shell command with 20-minute timeout)
     Shell(command="vng -v --build --configitem CONFIG_KASAN=y", timeout=1200000)

     # STEP 2: TEST (run_kernel tool or shell command)
     script -q -c "vng -- dmesg | grep -i kasan" /dev/null 2>&1

     Example 2: Remote build + local test
     ─────────────────────────────────────
     # STEP 1: BUILD on remote host (shell command with 20-minute timeout)
     Shell(command="vng -v --build --build-host builder", timeout=1200000)

     # STEP 2: TEST locally (run_kernel tool or shell command)
     script -q -c "vng -- uname -r" /dev/null 2>&1

     Example 3: Remote build with config + test
     ───────────────────────────────────────────
     # STEP 1: BUILD on remote host (shell command with 20-minute timeout)
     Shell(command="vng -v --build --build-host myserver --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

     # STEP 2: TEST (run_kernel tool or shell command)
     script -q -c "vng -- cat /proc/version" /dev/null 2>&1

     ⚠️  REMEMBER: All build commands MUST use timeout=1200000 (or higher)!

5. MCP Tools Available
   --------------------
   This MCP server provides:
   - configure_kernel: Generate/modify kernel .config
   - run_kernel: Run and test kernels in QEMU
   - get_kernel_info: Get info about kernel source directory
   - apply_patch: Apply patches from lore.kernel.org

   For building, use shell commands with 'vng -v --build' as documented above.
"""

import asyncio
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    print(
        "Error: mcp package not found. Install it with: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# Initialize the MCP server
app = Server("virtme-ng")


def run_command(
    cmd: list[str], cwd: str | None = None, timeout: int = 3600
) -> tuple[int, str, str]:
    """
    Execute a command and return the result.

    Args:
        cmd: Command and arguments as a list
        cwd: Working directory (defaults to current directory)
        timeout: Command timeout in seconds (default: 1 hour)

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout} seconds"
    except Exception as e:  # pylint: disable=broad-exception-caught
        return -1, "", f"Error executing command: {str(e)}"


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for kernel development."""
    return [
        Tool(
            name="configure_kernel",
            description="""
Configure a Linux kernel for virtme-ng testing.
This generates a minimal .config file optimized for quick builds and testing in QEMU.

NOTE: This step is OPTIONAL. The 'vng -v --build' command automatically
generates a .config if one doesn't exist, so you can skip this tool and go
straight to building with:

  vng -v --build

Use this tool only if you need to pre-configure the kernel before building, or if you
want to generate a .config without building yet.

Parameters:
- kernel_dir: Path to kernel source directory (default: current directory)
- arch: Target architecture (amd64, arm64, armhf, ppc64el, s390x, riscv64)
- config_fragments: List of additional config fragment files to apply
- config_items: List of specific CONFIG_ITEM=value settings to apply
- force: Force override existing config (default: false)
- verbose: Enable verbose output (default: false)

Returns: Configuration result with status and any error messages.

Example use cases:
- Generate default config: configure_kernel({})
- Custom config: configure_kernel({"config_items": ["CONFIG_DEBUG_INFO=y", "CONFIG_KASAN=y"]})
- Cross-compile: configure_kernel({"arch": "arm64"})

RECOMMENDED: Skip this tool and use 'vng -v --build' directly with --configitem options:

  Local build (with proper timeout!):
    Shell(command="vng -v --build --configitem CONFIG_DEBUG_INFO=y --configitem CONFIG_KASAN=y", timeout=1200000)

  Remote build (when user specifies a build server/host):
    Shell(command="vng -v --build --build-host <hostname> --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

  ⚠️ IMPORTANT: ALWAYS add --build-host when user mentions:
    • "build on <hostname>"
    • "compile on remote server"
    • "use my build machine"
    • Any reference to a remote build host

  ⏱️ TIMEOUT: Builds take 10-60+ minutes! Always use timeout=1200000ms (20 min) or higher!
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                    "arch": {
                        "type": "string",
                        "description": "Target architecture",
                        "enum": [
                            "amd64",
                            "arm64",
                            "armhf",
                            "ppc64el",
                            "s390x",
                            "riscv64",
                        ],
                    },
                    "config_fragments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of config fragment file paths",
                    },
                    "config_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of CONFIG_ITEM=value settings",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force override existing config",
                        "default": False,
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Enable verbose output",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="run_kernel",
            description="""
Run/test a Linux kernel in a virtualized environment using virtme-ng.
The kernel runs in QEMU with a copy-on-write snapshot of your live system.

╔═══════════════════════════════════════════════════════════════════════════╗
║ ⚠️  CRITICAL: THIS TOOL IS FOR TESTING/RUNNING KERNELS ONLY                ║
║                                                                           ║
║ DO NOT USE run_kernel TO BUILD KERNELS!                                   ║
║                                                                           ║
║ To build kernels, use shell commands with 'vng -v --build':               ║
║   • Local build:        vng -v --build                                    ║
║   • Remote build:       vng -v --build --build-host <hostname>            ║
║                                                                           ║
║ This tool (run_kernel) ONLY runs/tests already-built kernels.             ║
╚═══════════════════════════════════════════════════════════════════════════╝

╔═══════════════════════════════════════════════════════════════════════════╗
║ 🔴 CRITICAL: EACH INVOCATION CREATES A NEW, INDEPENDENT VM INSTANCE!      ║
║                                                                           ║
║ Every run_kernel() call spawns a FRESH virtual machine. State does NOT    ║
║ persist between calls. You CANNOT run a command and check dmesg in a      ║
║ separate invocation - they are COMPLETELY DIFFERENT VMs!                  ║
║                                                                           ║
║ ✅ CORRECT (single invocation, single VM):                                ║
║    run_kernel({"command": "insmod test.ko && dmesg | grep test"})         ║
║                                                                           ║
║ ❌ WRONG (two invocations = two different VMs):                           ║
║    run_kernel({"command": "insmod test.ko"})         # VM #1              ║
║    run_kernel({"command": "dmesg | grep test"})      # VM #2 (fresh!)     ║
║    ↑ The dmesg output will NOT contain anything from the first command!   ║
║                                                                           ║
║ SOLUTION: Use && or ; to combine commands into a single invocation:       ║
║   • cmd1 && cmd2  → Run cmd2 only if cmd1 succeeds                        ║
║   • cmd1 ; cmd2   → Run both commands sequentially                        ║
║   • cmd1 || cmd2  → Run cmd2 only if cmd1 fails                           ║
║                                                                           ║
║ Each run_kernel() call = boot VM → run command → capture output → exit    ║
║ No state carries over between invocations!                                ║
╚═══════════════════════════════════════════════════════════════════════════╝

AI agents should use this tool rather than running vng directly via shell commands.
If you must use shell commands, use 'script': script -q -c "vng -- command" /dev/null 2>&1

WORKFLOW - Build FIRST, then Test:
====================================
1. BUILD the kernel (use shell command, NOT this tool):

   ⏱️  CRITICAL: Builds take 10-60+ minutes! Use timeout=1200000 or higher!

   • For local builds:
     Shell(command="vng -v --build", timeout=1200000)

   • For REMOTE builds (when user specifies a build server/host):
     Shell(command="vng -v --build --build-host <hostname>", timeout=1200000)

     Examples of when to use --build-host:
     - User says: "build on my server called 'builder'"
     - User says: "compile on remote host 'myserver'"
     - User says: "use the build machine to compile"
     - User says: "build this on <hostname>"

   • With custom config:
     Shell(command="vng -v --build --configitem CONFIG_DEBUG_INFO=y", timeout=1200000)

   • Remote build with custom config:
     Shell(command="vng -v --build --build-host builder --configitem CONFIG_KASAN=y", timeout=1200000)

2. TEST the kernel (use THIS tool):
   After building, use run_kernel() to test the built kernel.

IMPORTANT - Understanding which kernel runs:
1. WITHOUT kernel_image parameter (recommended for testing built kernels):
   - Syntax: vng -- <command>
   - Runs the NEWLY BUILT kernel in the current kernel source directory
   - Use this to test kernels you just compiled

2. WITH kernel_image set to "host":
   - Syntax: vng -vr -- <command>
   - Runs the HOST kernel (currently running on the system)
   - Use this to test commands in the production kernel environment

3. WITH kernel_image set to an UPSTREAM VERSION (e.g., "v6.14", "v6.6.17"):
   - Syntax: vng -vr v6.14 -- <command>
   - AUTOMATICALLY DOWNLOADS and runs a precompiled upstream kernel from Ubuntu
     mainline
   - Very useful for testing against different kernel versions without building
   - Format: "v" + version number (e.g., "v6.14", "v6.6.17", "v6.12-rc3")

4. WITH kernel_image set to a SPECIFIC PATH:
   - Syntax: vng -vr <path> -- <command>
   - Runs a specific kernel image file (e.g., "./arch/x86/boot/bzImage")
   - Use this to test a particular local kernel build

Parameters:
- kernel_dir: Path to kernel source directory (default: current directory)
- kernel_image: Controls which kernel to run:
  * omit/null = run newly built kernel in current dir (DEFAULT - use this for testing your builds)
  * "host" = run the host kernel currently running on the system
  * "v6.14" (or any vX.Y version) = download and run upstream kernel from Ubuntu mainline (auto-download)
  * "./path/to/bzImage" = run specific local kernel image file
- command: Command to execute inside the kernel (kernel exits after execution)
- arch: Architecture to emulate
- cpus: Number of CPUs for the VM (default: all host CPUs)
- memory: Memory size for the VM (default: 1G)
- timeout: Maximum runtime in seconds (default: 300 for commands, unlimited for interactive)
- network: Enable network ("user", "bridge", "loop")
- debug: Enable kernel debugging features

Returns: Execution result with kernel output, exit code, and any error messages.

Example use cases:
- Test newly built kernel: run_kernel({"command": "uname -r"})
  → Runs: vng -v -- uname -r (tests your compiled kernel)

- Test on host kernel: run_kernel({"kernel_image": "host", "command": "uname -r"})
  → Runs: vng -vr -- uname -r (tests current system kernel)

- Test upstream kernel (auto-download): run_kernel({"kernel_image": "v6.14", "command": "uname -r"})
  → Runs: vng -vr v6.14 -- uname -r (downloads v6.14 from Ubuntu mainline if not cached)

- Test specific upstream version: run_kernel({"kernel_image": "v6.6.17", "command": "uname -a"})
  → Runs: vng -vr v6.6.17 -- uname -a (downloads and runs v6.6.17)

- Test local kernel image: run_kernel({"kernel_image": "./arch/x86/boot/bzImage", "command": "uname -r"})
  → Runs: vng -vr ./arch/x86/boot/bzImage -- uname -r

- Run test suite on your kernel: run_kernel({"command": "cd /path/to/tests && ./run_tests.sh"})
  → Runs: vng -v -- cd /path/to/tests && ./run_tests.sh

- Compare behavior across versions:
  1) run_kernel({"command": "cat /proc/version"}) - your build
  2) run_kernel({"kernel_image": "v6.14", "command": "cat /proc/version"}) - upstream v6.14
  3) run_kernel({"kernel_image": "host", "command": "cat /proc/version"}) - host kernel
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                    "kernel_image": {
                        "type": "string",
                        "description": (
                            "Which kernel to run: omit for newly built kernel "
                            "(DEFAULT), 'host' for host kernel, 'v6.14' for upstream "
                            "auto-download, or './path' for local image"
                        ),
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute inside the kernel",
                    },
                    "arch": {
                        "type": "string",
                        "description": "Target architecture",
                        "enum": [
                            "amd64",
                            "arm64",
                            "armhf",
                            "ppc64el",
                            "s390x",
                            "riscv64",
                        ],
                    },
                    "cpus": {
                        "type": "integer",
                        "description": "Number of CPUs",
                    },
                    "memory": {
                        "type": "string",
                        "description": "Memory size (e.g., '2G', '512M')",
                        "default": "1G",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum runtime in seconds",
                    },
                    "network": {
                        "type": "string",
                        "description": "Network mode",
                        "enum": ["user", "bridge", "loop"],
                    },
                    "debug": {
                        "type": "boolean",
                        "description": "Enable debugging features",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="get_kernel_info",
            description="""
Get information about the kernel source directory.
Returns details like kernel version, git commit, dirty status, etc.

Parameters:
- kernel_dir: Path to kernel source directory (default: current directory)

Returns: JSON object with kernel information including:
- version: Kernel version string
- git_commit: Current git commit hash (if git repo)
- git_branch: Current git branch (if git repo)
- is_dirty: Whether there are uncommitted changes
- config_exists: Whether .config file exists
- architecture: Detected architecture from .config

NOTE: If config_exists is false, the kernel hasn't been configured/built yet.
Use shell command to build it: script -q -c "vng -v --build" /dev/null 2>&1

Example:
- get_kernel_info({})
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                },
            },
        ),
        Tool(
            name="apply_patch",
            description="""
Apply a patch from lore.kernel.org using b4 shazam.
This tool downloads and applies kernel patches from the lore.kernel.org mailing list archive.

b4 shazam will:
1. Download the patch series from lore.kernel.org using the message ID
2. Apply the patches directly to the current git tree
3. Create git commits with proper authorship and metadata

Parameters:
- message_id: Message ID from lore.kernel.org (required)
  Example: "20251029191111.167537-1-arighi@nvidia.com"
  The message ID can be found in the URL of a lore.kernel.org email or in the Message-Id header
- kernel_dir: Path to kernel source directory (default: current directory)

Returns: Result with success status, applied patches information, and any error messages.

Example use cases:
- Apply a patch: apply_patch({"message_id": "20251029191111.167537-1-arighi@nvidia.com"})

Requirements:
- b4 tool must be installed (pip install b4)
- Must be run in a git repository with a clean working tree
- Git must be configured with user.name and user.email
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": (
                            "Message ID from lore.kernel.org "
                            "(e.g., 20251029191111.167537-1-arighi@nvidia.com)"
                        ),
                    },
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                },
                "required": ["message_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls from the MCP client."""

    if name == "configure_kernel":
        return await configure_kernel(arguments)
    if name == "run_kernel":
        return await run_kernel(arguments)
    if name == "get_kernel_info":
        return await get_kernel_info(arguments)
    if name == "apply_patch":
        return await apply_patch(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def configure_kernel(args: dict) -> list[TextContent]:
    """Configure the kernel using virtme-configkernel."""
    kernel_dir = args.get("kernel_dir", ".")

    # Build the vng command
    cmd = ["vng", "--kconfig"]

    if args.get("force"):
        cmd.append("--force")

    if args.get("verbose"):
        cmd.append("--verbose")

    if args.get("arch"):
        cmd.extend(["--arch", args["arch"]])

    if args.get("config_fragments"):
        for fragment in args["config_fragments"]:
            cmd.extend(["--config", fragment])

    if args.get("config_items"):
        for item in args["config_items"]:
            cmd.extend(["--configitem", item])

    # Execute the command
    returncode, stdout, stderr = run_command(cmd, cwd=kernel_dir)

    # Build the response
    result = {
        "success": returncode == 0,
        "command": shlex.join(cmd),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

    if returncode == 0:
        config_path = Path(kernel_dir) / ".config"
        if config_path.exists():
            result["config_file"] = str(config_path)
            result["message"] = "Kernel configuration completed successfully"
        else:
            result["message"] = "Configuration command succeeded but .config not found"
    else:
        result["message"] = "Kernel configuration failed"

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def run_kernel(args: dict) -> list[TextContent]:
    """Run the kernel using vng with output redirection to handle PTS requirement."""
    kernel_dir = args.get("kernel_dir", ".")

    # Build the vng command
    vng_cmd = ["vng"]

    # Determine which kernel to run based on kernel_image parameter
    kernel_image = args.get("kernel_image")

    if kernel_image == "host":
        # Run host kernel: vng -r -- <command>
        vng_cmd.append("-vr")
    elif kernel_image:
        # Run specific kernel: vng -r <image> -- <command>
        vng_cmd.extend(["-vr", kernel_image])

    if args.get("arch"):
        vng_cmd.extend(["--arch", args["arch"]])

    if args.get("cpus"):
        vng_cmd.extend(["--cpus", str(args["cpus"])])

    if args.get("memory"):
        vng_cmd.extend(["--memory", args["memory"]])

    if args.get("network"):
        vng_cmd.extend(["--network", args["network"]])

    if args.get("debug"):
        vng_cmd.append("--debug")

    # Add command to execute using -- separator (modern syntax)
    # The -- separates vng options from the command to run in the kernel
    if args.get("command"):
        vng_cmd.append("--")
        vng_cmd.append(args["command"])

    # Determine timeout
    if args.get("timeout"):
        timeout = args["timeout"]
    elif args.get("command"):
        # If running a command, use shorter default timeout
        timeout = 300  # 5 minutes
    else:
        # Interactive mode - not recommended for agents
        timeout = 60  # 1 minute for safety

    # IMPORTANT: vng requires a valid PTS (pseudo-terminal).
    # In automated environments, we must use 'script' to provide a PTS.
    # Use: script -q -c "vng ..." /dev/null 2>&1

    # Construct the vng command string
    vng_cmd_str = shlex.join(vng_cmd)

    # Wrap vng command in 'script' to provide a pseudo-terminal
    # script -q: quiet mode (no start/stop messages)
    # script -c: execute command
    # /dev/null: discard the typescript file
    shell_cmd = f"script -q -c {shlex.quote(vng_cmd_str)} /dev/null 2>&1"

    # Execute the command with script wrapper
    start_time = time.time()
    returncode, stdout, stderr = run_command(
        ["sh", "-c", shell_cmd], cwd=kernel_dir, timeout=timeout
    )
    run_time = time.time() - start_time

    # Build the response
    result = {
        "success": returncode == 0,
        "command": vng_cmd_str,  # Show the actual vng command (without script wrapper)
        "shell_command": shell_cmd,  # Show the full shell command with script wrapper
        "returncode": returncode,
        "run_time_seconds": round(run_time, 2),
        "stdout": stdout,
        "stderr": stderr,
        "pts_workaround": "Using 'script' command to provide pseudo-terminal for vng",
    }

    # Add context about which kernel was run
    if not kernel_image:
        result["kernel_type"] = "newly_built_kernel"
        result["note"] = "Ran newly built kernel in the current directory"
    elif kernel_image == "host":
        result["kernel_type"] = "host_kernel"
        result["note"] = "Ran host kernel (currently running on system)"
    elif kernel_image.startswith("v") and any(c.isdigit() for c in kernel_image):
        # Looks like an upstream version (e.g., v6.14, v6.6.17, v6.12-rc3)
        result["kernel_type"] = "upstream_kernel"
        result["kernel_version"] = kernel_image
        result["note"] = (
            f"Ran upstream kernel {kernel_image} (auto-downloaded from Ubuntu mainline if not cached)"
        )
    else:
        # Likely a path to a specific kernel image
        result["kernel_type"] = "local_kernel_image"
        result["kernel_image"] = kernel_image
        result["note"] = f"Ran local kernel image: {kernel_image}"

    if returncode == 0:
        result["message"] = "Kernel execution completed successfully"
    elif returncode == -1:
        result["message"] = "Kernel execution timed out or failed"
    else:
        result["message"] = f"Kernel execution failed with exit code {returncode}"

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def get_kernel_info(args: dict) -> list[TextContent]:
    """Get information about the kernel source directory."""
    kernel_dir = args.get("kernel_dir", ".")
    kernel_path = Path(kernel_dir)

    info = {
        "kernel_dir": str(kernel_path.absolute()),
        "exists": kernel_path.exists(),
    }

    if not kernel_path.exists():
        info["error"] = "Kernel directory does not exist"
        return [TextContent(type="text", text=json.dumps(info, indent=2))]

    # Check if it's a git repository
    git_dir = kernel_path / ".git"
    if git_dir.exists():
        info["is_git_repo"] = True

        # Get git commit
        returncode, stdout, _ = run_command(
            ["git", "rev-parse", "HEAD"], cwd=kernel_dir, timeout=10
        )
        if returncode == 0:
            info["git_commit"] = stdout.strip()
            info["git_commit_short"] = stdout.strip()[:12]

        # Get git branch
        returncode, stdout, _ = run_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=kernel_dir, timeout=10
        )
        if returncode == 0:
            info["git_branch"] = stdout.strip()

        # Check if dirty
        returncode, stdout, _ = run_command(
            ["git", "status", "--porcelain"], cwd=kernel_dir, timeout=10
        )
        if returncode == 0:
            info["is_dirty"] = len(stdout.strip()) > 0
    else:
        info["is_git_repo"] = False

    # Check for .config
    config_file = kernel_path / ".config"
    info["config_exists"] = config_file.exists()

    if config_file.exists():
        # Try to detect architecture from config
        try:
            with open(config_file, encoding="utf-8") as f:
                content = f.read()
                if "CONFIG_X86_64=y" in content:
                    info["config_arch"] = "x86_64"
                elif "CONFIG_ARM64=y" in content:
                    info["config_arch"] = "arm64"
                elif "CONFIG_ARM=y" in content:
                    info["config_arch"] = "arm"
                elif "CONFIG_PPC64=y" in content:
                    info["config_arch"] = "ppc64"
                elif "CONFIG_RISCV=y" in content:
                    info["config_arch"] = "riscv64"
                elif "CONFIG_S390=y" in content:
                    info["config_arch"] = "s390x"
        except Exception as e:  # pylint: disable=broad-exception-caught
            info["config_read_error"] = str(e)

    # Try to get kernel version from Makefile
    makefile = kernel_path / "Makefile"
    if makefile.exists():
        try:
            with open(makefile, encoding="utf-8") as f:
                lines = f.readlines()[:10]  # Version is typically in first 10 lines
                version_parts = {}
                for line in lines:
                    if line.startswith("VERSION ="):
                        version_parts["major"] = line.split("=")[1].strip()
                    elif line.startswith("PATCHLEVEL ="):
                        version_parts["minor"] = line.split("=")[1].strip()
                    elif line.startswith("SUBLEVEL ="):
                        version_parts["patch"] = line.split("=")[1].strip()

                if version_parts:
                    major = version_parts.get("major", "?")
                    minor = version_parts.get("minor", "?")
                    patch = version_parts.get("patch", "?")
                    info["kernel_version"] = f"{major}.{minor}.{patch}"
        except Exception as e:  # pylint: disable=broad-exception-caught
            info["version_read_error"] = str(e)

    return [TextContent(type="text", text=json.dumps(info, indent=2))]


async def apply_patch(args: dict) -> list[TextContent]:
    """Apply a patch from lore.kernel.org using b4 shazam."""
    kernel_dir = args.get("kernel_dir", ".")
    message_id = args.get("message_id")

    if not message_id:
        result = {
            "success": False,
            "error": "message_id is required",
            "message": "Please provide a message ID from lore.kernel.org",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if b4 is installed
    returncode, stdout, stderr = run_command(["which", "b4"], timeout=5)
    if returncode != 0:
        result = {
            "success": False,
            "error": "b4 not found",
            "message": "b4 tool is not installed. Install it with: pip install b4",
            "help": "b4 is required to download and apply patches from lore.kernel.org",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if we're in a git repository
    kernel_path = Path(kernel_dir)
    git_dir = kernel_path / ".git"
    if not git_dir.exists():
        result = {
            "success": False,
            "error": "not_a_git_repo",
            "message": f"Directory {kernel_dir} is not a git repository",
            "help": "b4 shazam requires a git repository to apply patches",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Build the b4 shazam command
    cmd = ["b4", "shazam"]

    # Add the message ID
    cmd.append(message_id)

    # Execute the command
    returncode, stdout, stderr = run_command(cmd, cwd=kernel_dir, timeout=300)

    # Build the response
    result = {
        "success": returncode == 0,
        "command": shlex.join(cmd),
        "message_id": message_id,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

    if returncode == 0:
        result["message"] = f"Successfully applied patch series from {message_id}"

        # Try to extract information about applied patches from stdout
        if "Applying:" in stdout or "Applied" in stdout:
            result["note"] = "Patches have been applied and committed to the git tree"
    else:
        result["message"] = f"Failed to apply patch series from {message_id}"

        # Provide helpful error messages for common issues
        if "fatal: not a git repository" in stderr:
            result["help"] = "Make sure you're in a git repository"
        elif "working tree is not clean" in stderr or "has unstaged changes" in stderr:
            result["help"] = (
                "Git working tree must be clean. Commit or stash your changes first"
            )
        elif "Cannot find" in stdout or "not found" in stdout:
            result["help"] = (
                "Message ID not found on lore.kernel.org. Check that the message ID is correct"
            )
        elif "Unable to apply" in stdout or "conflict" in stdout.lower():
            result["help"] = (
                "Patch failed to apply. There may be merge conflicts or the patch is for a different kernel version"
            )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def run_mcp_server():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    """Main entry point when run as a module."""
    try:
        asyncio.run(run_mcp_server())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # pylint: disable=broad-exception-caught
        sys.stderr.write(f"Error: {str(e)}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
