# -*- mode: python -*-
# Copyright 2025 Andrea Righi <arighi@nvidia.com>

"""
MCP Server for virtme-ng - Kernel development and testing tools
Provides tools for AI agents to configure and test Linux kernels

IMPORTANT NOTES FOR AI AGENTS:
================================

1. BUILDING KERNELS - CRITICAL INSTRUCTIONS
   ==========================================

   ⚠️  NEVER use the run_kernel_cmd tool to build kernels!
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

   ⚠️  ALWAYS use sufficient timeout for builds
   ⚠️  For faster builds, use remote hosts with --build-host option

   Why use vng -v --build:
   - Automatically generates minimal .config if missing (saves time)
   - Optimized for quick builds (compiles only what's needed for testing)
   - Builds typically complete in minutes instead of hours
   - Supports remote build hosts for cross-compilation
   - Handles all build dependencies and options correctly

   Basic build command:
     vng -v --build

   Build specific commit/tag:
     vng -v --build --commit v6.2-rc4

   Build with custom config items:
     vng -v --build --configitem CONFIG_KASAN=y --configitem CONFIG_DEBUG_INFO=y

   Build on remote host "builder" (for cross-compilation or distributed builds):
     vng -v --build --build-host builder

   Build with environment variables (e.g., Rust support):
     vng -v --build RUSTC=rustc-1.62 BINDGEN=bindgen-0.56

   Build for different architecture:
     vng -v --build --arch arm64 --root /opt/chroot/arm64/

   ⚠️  CRITICAL TIMEOUT WARNING:
   ────────────────────────────
   vng -v --build can take a long time to complete!

   For faster builds, consider:
   • Building on a faster remote host with --build-host
   • Using incremental builds when possible

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

   Examples:
     vng -v --build --build-host myserver
     vng -v --build --build-host builder
     vng -v --build --build-host builder --arch arm64
     vng -v --build --build-host myserver --configitem CONFIG_DEBUG_INFO=y

2. EACH run_kernel_cmd INVOCATION SPAWNS A NEW, INDEPENDENT VM
   ==================================================================

   ⚠️  CRITICAL: Every call to run_kernel_cmd() creates a FRESH, ISOLATED VM instance!

   This means:
   ✗ State does NOT persist between run_kernel_cmd invocations
   ✗ You CANNOT run a command and then check dmesg in a separate invocation
   ✗ You CANNOT set up something in one call and use it in another
   ✗ Each VM starts fresh with no memory of previous invocations

   ✓ CORRECT: Combine commands in a SINGLE run_kernel_cmd invocation:
     run_kernel_cmd({"command": "some_command && dmesg | grep -i warning"})
     run_kernel_cmd({"command": "modprobe mymod && cat /sys/module/mymod/parameters/debug"})
     run_kernel_cmd({"command": "cd /tmp && echo test > file && cat file"})

   ✗ WRONG: Multiple separate invocations (these are INDEPENDENT VMs!):
     run_kernel_cmd({"command": "some_command"})        # VM instance #1
     run_kernel_cmd({"command": "dmesg"})               # VM instance #2 (different VM!)
     # These two commands run in COMPLETELY DIFFERENT virtual machines!
     # The dmesg output will NOT contain anything from the first command!

   WHY THIS MATTERS:
   - run_kernel_cmd() returns a command that starts a QEMU VM, runs the command, captures output, then EXITS
   - Each invocation = fresh boot, fresh memory, fresh state
   - Like rebooting a computer between each command

   EXAMPLES:

   ❌ BAD - Won't work (separate VMs):
      run_kernel_cmd({"command": "insmod mymodule.ko"})
      run_kernel_cmd({"command": "dmesg | grep mymodule"})  # Won't see module from first call!

   ✅ GOOD - Works (single VM):
      run_kernel_cmd({"command": "insmod mymodule.ko && dmesg | grep mymodule"})

   ❌ BAD - Won't work (separate VMs):
      run_kernel_cmd({"command": "echo 1 > /proc/sys/kernel/printk"})
      run_kernel_cmd({"command": "cat /proc/sys/kernel/printk"})  # Will show default, not 1!

   ✅ GOOD - Works (single VM):
      run_kernel_cmd({"command": "echo 1 > /proc/sys/kernel/printk && cat /proc/sys/kernel/printk"})

   SHELL OPERATORS for combining commands:
   - && : Run second command only if first succeeds
   - ;  : Run commands sequentially regardless of success
   - || : Run second command only if first fails

   Example with complex script:
     run_kernel_cmd({"command": "cd /path && ./test.sh && dmesg | tail -50"})

3. PTS (Pseudo-Terminal) Requirement
   -----------------------------------
   virtme-ng (vng) requires a valid pseudo-terminal (PTS) to run. In automated
   environments without a real terminal, vng commands will fail with:
     "ERROR: not a valid pts, try to run vng with a valid PTS (e.g., inside tmux or screen)"

   This MCP server's run_kernel_cmd tool automatically handles PTS requirements by wrapping
   commands with 'script'.

   For direct shell commands, use 'script' to provide a PTS:
     script -q -c "vng -- command" /dev/null 2>&1

   The 'script' command:
     -q: Quiet mode (no script start/stop messages)
     -c: Execute command and exit
     /dev/null: Discard the typescript file (we only need stdout/stderr)

4. Typical Workflow for Testing Kernel Changes
   ============================================

   STEP 1: BUILD (use build_kernel tool or shell command, NOT run_kernel_cmd tool!)
   ────────────────────────────────────────────────────────

   ⏱️  TIMEOUT REQUIREMENT: Builds take a long time (use sufficient timeout)

   a) Local build:
      vng -v --build
      (NEVER use: make -j$(nproc), ALWAYS use: vng -v --build)

   b) Remote build (when user specifies a hostname/server):
      vng -v --build --build-host <hostname>

   c) Build with custom config:
      vng -v --build --configitem CONFIG_KASAN=y

   d) Remote build with custom config:
      vng -v --build --build-host builder --configitem CONFIG_DEBUG_INFO=y

   STEP 2: TEST (use run_kernel_cmd tool or shell command)
   ────────────────────────────────────────────────────

   After building, test the kernel:
   • Use run_kernel_cmd tool to get the command, then execute it with Shell tool, OR
   • Use shell command directly: script -q -c "vng -- uname -r" /dev/null 2>&1

   ═══════════════════════════════════════════════════════════════════
   COMPLETE WORKFLOW EXAMPLES (with proper timeouts!):
   ═══════════════════════════════════════════════════════════════════

     Example 1: Local build + test with KASAN
     ─────────────────────────────────────────
    # STEP 1: BUILD
    vng -v --build --configitem CONFIG_KASAN=y

     # STEP 2: TEST (shell command)
     script -q -c "vng -- dmesg | grep -i kasan" /dev/null 2>&1

     Example 2: Remote build + local test
     ─────────────────────────────────────
    # STEP 1: BUILD on remote host
    vng -v --build --build-host builder

     # STEP 2: TEST locally (shell command)
     script -q -c "vng -- uname -r" /dev/null 2>&1

    Example 3: Remote build with config + test
    ───────────────────────────────────────────
    # STEP 1: BUILD on remote host
    vng -v --build --build-host myserver --configitem CONFIG_DEBUG_INFO=y

    # STEP 2: TEST (shell command)
    script -q -c "vng -- cat /proc/version" /dev/null 2>&1

5. Running Kernel Selftests (kselftests)
   ======================================

   WORKFLOW FOR AI AGENTS - How to run kselftests with virtme-ng:
   ──────────────────────────────────────────────────────────────

   ⚠️  IMPORTANT: Build the kernel FIRST!
   vng -v --build

   Then use run_kselftest_cmd to get a script and command to execute:
   1. Call run_kselftest_cmd() to get a single command
   2. IMMEDIATELY execute the command using Shell tool in the SAME response
   3. That's it!

   ⚠️  IMPORTANT: Always execute the returned command immediately - do NOT wait for user input!

   BASIC USAGE
   ───────────
   # Get the command to run
   result = run_kselftest_cmd({"test_name": "sched_ext"})

   # result contains:
   # {
   #   "success": true,
   #   "command": "bash /path/to/kernel/vng-kselftest.sh",
   #   "action_required": "EXECUTE_NOW",
   #   "description": "Run kselftest sched_ext"
   # }

   # IMMEDIATELY execute the command in the same response - do NOT wait!
   Shell(command=result["command"])

   The run_kselftest_cmd tool returns:
   - A single command that executes a script
   - The script handles all steps automatically (headers, build, test)

   ⏱️ TIMING:
   ──────────
  - Kselftests can take 10+ minutes depending on the test suite
  - Builds can take 5-10 minutes
  - Execute the command using Shell tool which handles timeouts automatically

   COMPLETE EXAMPLES:
   ──────────────────

   Example 1: Run sched_ext tests
   ──────────────────────────────
   # STEP 1: Build kernel first!
   vng -v --build

   # STEP 2: Get command to run
   result = run_kselftest_cmd({"test_name": "sched_ext"})

   # STEP 3: Execute the command
   Shell(command=result["command"])
   # The script automatically handles all steps!

   Example 2: Run tests on HOST kernel
   ────────────────────────────────────
   # Get command - only builds kselftest, skips kernel rebuild
   result = run_kselftest_cmd({
       "test_name": "net",
       "kernel_image": "host"
   })

   # Execute command
   Shell(command=result["command"])

   Example 3: Run tests on UPSTREAM kernel
   ────────────────────────────────────────
   # Get command - builds kselftest and uses upstream kernel
   result = run_kselftest_cmd({
       "test_name": "seccomp",
       "kernel_image": "v6.14"
   })

   # Execute command
   Shell(command=result["command"])

6. MCP Tools Available
   --------------------
   This MCP server provides:
   - configure_kernel: Generate/modify kernel .config
   - run_kernel_cmd: Generate command for running kernel tests
   - run_kselftest_cmd: Generate script and return command for running kernel selftests (RECOMMENDED for kselftests)
   - get_kernel_info: Get info about kernel source directory
   - apply_patch: Apply patches from lore.kernel.org

   Tools return a single command that you execute directly using Shell tool.
   This is simple and works great with all AI models!

   How it works:
   ─────────────
   For complex operations (like run_kselftest_cmd), the tool creates a script (vng-kselftest.sh)
   in the kernel workspace that handles all the steps automatically, and returns a single
   command to execute it. The agent MUST execute this command immediately.

   You just execute the command - the script does everything:
   ✓ Install dependencies
   ✓ Build components
   ✓ Run the actual test

   No need to manage multiple commands or worry about execution order!

   For building kernels, use shell commands with 'vng -v --build' as documented above.
   For running kselftests, use the run_kselftest_cmd tool (see section 5).
   For validating patch series, see section 7 below.

   ⚠️  CRITICAL WARNING: Architecture Parameter (--arch)
   ══════════════════════════════════════════════════════
   NEVER set the 'arch' parameter unless the user EXPLICITLY requests a specific architecture!

   When to set arch (rare):
   ✓ User explicitly says: "test on arm64"
   ✓ User explicitly says: "build for riscv64"
   ✓ User explicitly says: "cross-compile to aarch64"

   When NOT to set arch (99% of cases):
   ✗ User says: "build and test the kernel"
   ✗ User says: "run kselftests"
   ✗ User says: "test this patch"
   ✗ ANY request that doesn't explicitly mention an architecture

   If arch is omitted, the tool automatically uses the host architecture (which is correct).
   Setting arch unnecessarily triggers cross-compilation and requires special chroot setup!

7. Validating Patch Series
   ========================================================

   When a user asks to validate a patch series by building and booting each commit,
   use a combination of Shell commands and run_kernel_cmd() for each commit.

   ⚠️  CRITICAL: ALWAYS BUILD **AND** BOOT EACH KERNEL
   ════════════════════════════════════════════════════
   - Building alone is NOT sufficient validation
   - EVERY kernel MUST be booted and tested inside virtme-ng
   - A kernel that builds but doesn't boot is a FAILED commit
   - NEVER skip the boot testing step

   ⚠️  WARNING: This operation can take HOURS (10-60+ minutes per commit)

   WORKFLOW: Build + Boot Each Commit
   ───────────────────────────────────

   For each commit in a series:
   1. Checkout the commit
   2. Build the kernel using: vng -v --build
   3. Boot and test using: run_kernel_cmd()
   4. Record BOTH build and boot results

   MANDATORY WORKFLOW:
   ───────────────────
   For each commit in the range, you MUST perform ALL these steps:
   1. Checkout the commit using git
   2. BUILD the kernel using: vng -v --build
   3. BOOT the kernel using run_kernel_cmd() - THIS STEP IS MANDATORY
   4. Record BOTH build and boot results (both must succeed)
   5. Return to original commit when done

   A commit is considered PASSED only if BOTH build AND boot succeed.

   STEP-BY-STEP IMPLEMENTATION (ALL STEPS MANDATORY):
   ──────────────────────────────────────────────────

   Step 1: Get the list of commits
   ────────────────────────────────
   git rev-list --reverse START_COMMIT^..END_COMMIT

   This returns a list of commit SHAs, one per line.

   Step 2: Save current state
   ───────────────────────────
   git rev-parse HEAD

   Save this to restore later.

   Step 3: For each commit, YOU MUST perform ALL these steps:
   ───────────────────────────────────────────────────────────

   a) Get commit info:
      git log -1 --format='%h - %s' COMMIT_SHA

   b) Checkout commit:
      git checkout COMMIT_SHA

   c) BUILD the kernel (REQUIRED):
      vng -v --build

      # Or with remote build host:
      vng -v --build --build-host builder

      # Or with custom config:
      vng -v --build --configitem CONFIG_KASAN=y

      If build fails: Record failure and continue (or stop if user requested)

   d) BOOT and TEST the kernel (REQUIRED - DO NOT SKIP):
      ⚠️  THIS STEP IS MANDATORY - A kernel that builds but doesn't boot is FAILED

      You MUST boot every successfully built kernel to verify it works.

      MINIMUM (always required): Verify kernel boots using shell command:
      script -q -c 'vng -- uname -r' /dev/null 2>&1

      OR with custom test command (if user specified):
      script -q -c 'vng -- user_test_command_here' /dev/null 2>&1

      OR use run_kernel_cmd() to get the command:
      result = run_kernel_cmd({"command": "uname -r"})
      # Execute: result["command"]

      ⚠️  If you skip this step, the validation is INCOMPLETE and INVALID

   e) Record result (BOTH build and boot required):
      - Record build result: SUCCESS or FAILED (exit code 0 vs non-zero)
      - Record boot result: SUCCESS or FAILED (exit code 0 vs non-zero)
      - A commit PASSES only if BOTH build AND boot succeed
      - A commit that builds but fails to boot is considered FAILED
      - Store commit SHA, subject, build result, and boot result

   Step 4: Restore original state
   ───────────────────────────────
   git checkout ORIGINAL_SHA

   Step 5: Report results
   ───────────────────────
   Summarize which commits passed/failed with a clear table or list.

   EXAMPLE INTERACTION:
   ────────────────────

   User: "Validate that each commit between HEAD~3 and HEAD builds and boots"

   AI MUST do ALL of the following:
   1. Get commits: git rev-list --reverse HEAD~3^..HEAD
   2. Save current: git rev-parse HEAD
   3. For EACH commit (ALL steps required):
      - Checkout commit: git checkout <sha>
      - BUILD: vng -v --build
      - If build succeeds, BOOT (MANDATORY): script -q -c 'vng -- uname -r' /dev/null 2>&1
      - If build fails, mark as FAILED and skip boot (or stop if requested)
      - Record: "✅ abc123 - Fix bug: Build OK, Boot OK"
                or "❌ def456 - Add feature: Build OK, Boot FAILED"
                or "❌ ghi789 - Update: Build FAILED (boot not tested)"
   4. Restore: git checkout <original>
   5. Report: "Validated 4 commits: 3 passed (build+boot), 1 failed"

   ⚠️  CRITICAL: Even if user just says "validate builds", you MUST test boots too!
   A kernel that compiles but doesn't boot is NOT validated.

   CRITICAL RULES FOR AI AGENTS:
   ─────────────────────────────
   ⚠️  MANDATORY: You MUST boot every successfully built kernel
       - Building alone is NOT validation
       - ALWAYS run boot test (script -q -c 'vng -- uname -r' /dev/null 2>&1) after successful build
       - A kernel that builds but doesn't boot is FAILED

  - Always save and restore the original git state
  - Use proper timeouts for builds
  - For faster builds, use --build-host if user mentions a build server
   - Show progress to the user after each commit (including boot status)
   - Provide a clear summary showing BOTH build and boot results
   - Handle failures gracefully - if a build fails, record it and continue (or stop if requested)
   - If boot fails after successful build, mark commit as FAILED

   EXAMPLE WITH REMOTE BUILD:
   ──────────────────────────

   User: "Validate HEAD~5 to HEAD using my build server 'builder'"

   For each commit:
   1. git checkout COMMIT
   2. vng -v --build --build-host builder
   3. If build succeeds: script -q -c 'vng -- uname -r' /dev/null 2>&1  ⚠️ MANDATORY
   4. Record both build and boot results

   EXAMPLE WITH CUSTOM TEST:
   ─────────────────────────

   User: "Validate these commits by running dmesg checks"

   For each commit:
   1. git checkout COMMIT
   2. vng -v --build
   3. If build succeeds: script -q -c 'vng -- dmesg | grep -i error || echo "No errors found"'
      /dev/null 2>&1  ⚠️ MANDATORY
   4. Record both build and boot/test results

   EXAMPLE WITH STOP ON FAILURE:
   ──────────────────────────────

   User: "Find which commit breaks the kernel between HEAD~20 and HEAD"

   For each commit:
   1. Build kernel: vng -v --build
   2. If build fails: report "First failing commit (build): COMMIT_SHA" and stop
   3. If build succeeds: Boot kernel: script -q -c 'vng -- uname -r' /dev/null 2>&1  ⚠️ MANDATORY
   4. If boot fails: report "First failing commit (boot): COMMIT_SHA" and stop
   5. If both succeed: continue to next commit

   IMPORTANT NOTES:
   ────────────────
   ⚠️  MOST IMPORTANT: ALWAYS test boot after every successful build
       - This is NOT optional - it's a required validation step
       - Use run_kernel_cmd({"command": "uname -r"}) at minimum
       - A commit that builds but doesn't boot is FAILED

   - Each commit needs a full rebuild (10-60+ minutes per commit)
   - Remote builds (--build-host) are much faster for patch series validation
   - Always restore the original git state, even if validation fails
   - Provide clear progress updates showing BOTH build and boot status
   - Handle git checkout failures gracefully (dirty working tree, etc.)
   - Report results as: "Build OK, Boot OK" or "Build FAILED" or "Build OK, Boot FAILED"
"""

import asyncio
import json
import os
import subprocess
import sys
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


def normalize_arch(arch: str | None) -> str | None:
    """
    Normalize architecture name to virtme-ng conventions.
    Converts x86/x86_64 to amd64.

    Args:
        arch: Architecture name (may be None)

    Returns:
        Normalized architecture name, or None if input was None
    """
    if arch is None:
        return None

    arch_lower = arch.lower()
    if arch_lower in ("x86", "x86_64"):
        return "amd64"

    return arch


def run_command(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """
    Execute a command and return the result.

    Args:
        cmd: Command and arguments as a list
        cwd: Working directory (defaults to current directory)

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
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

  Local build:
    vng -v --build --configitem CONFIG_DEBUG_INFO=y --configitem CONFIG_KASAN=y

  Remote build (when user specifies a build server/host):
    vng -v --build --build-host <hostname> --configitem CONFIG_DEBUG_INFO=y

  ⚠️ IMPORTANT: ALWAYS add --build-host when user mentions:
    • "build on <hostname>"
    • "compile on remote server"
    • "use my build machine"
    • Any reference to a remote build host

  ⏱️ TIMEOUT: Builds take 10-60+ minutes! Use sufficient timeout.
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
        Tool(
            name="run_kselftest_cmd",
            description="""
Generate a script and return command for running kernel selftests (kselftests).

🎯 KSELFTEST COMMAND GENERATOR - Build kernel first!
════════════════════════════════════════════════════════════
⚠  IMPORTANT: You must build the kernel BEFORE calling this!
    Use: vng -v --build

⚠  CRITICAL: This tool DOES NOT run the test - it returns a COMMAND that you MUST execute!

This tool creates a script (vng-kselftest.sh) in the kernel workspace and returns a single command to execute it.
The script handles all steps automatically:
1. Install kernel headers
2. Build the kselftest
3. Run the kselftest in VM

You just execute the single returned command using Shell tool - that's it!

Always set the minimum amount of arguments: when in doubt, don't set
additional arguments.

Just call: run_kselftest_cmd({"test_name": "sched_ext"})

WORKFLOW:
─────────
1. Call run_kselftest_cmd() to get a single command
2. IMMEDIATELY execute the command with Shell tool in the SAME response
3. Done!

⚠️  CRITICAL: You MUST execute the returned command immediately using Shell tool.
    Do NOT return the command to the user without executing it.
    Do NOT wait for user confirmation - execute it in the same tool call batch.
    THIS TOOL ONLY RETURNS A COMMAND - IT DOES NOT RUN THE TEST!

The command runs a script that handles all steps automatically:
- Installs kernel headers
- Builds the kselftest
- Runs the test in VM

You don't need to worry about multiple steps - the script does everything!

The returned command executes a script that handles:
- Installing kernel headers (if needed)
- Building the kselftest (if needed)
- Running the kselftest in VM with proper parameters

Just execute the single command using Shell tool - the script does all the work!

PARAMETERS:
───────────
- test_name (required): The kselftest target to run
  Examples: "sched_ext", "vm", "net", "seccomp", "livepatch"

- kernel_image (optional): Which kernel to run:
  * omit/null = run newly built kernel in current dir (DEFAULT)
  * "host" = run the host kernel currently running on the system
  * "v6.14" (or any vX.Y version) = download and run upstream kernel (auto-download)
  * "./path/to/bzImage" = run specific local kernel image file

- kernel_dir (optional): Path to kernel source directory (default: current directory)

- memory (optional): Memory size for VM (default: "2G")
  Increase for memory-intensive tests

- runner_args (optional): Additional arguments for kselftest runner (NEVER set unless specified by the user)
  Examples: "--verbose", "--tap", "--list"

- arch (optional): Target architecture to emulate
  ⚠️  WARNING: Do NOT set this parameter unless the user explicitly requests a specific architecture!
  Setting this can trigger cross-compilation and requires proper chroot setup.
  Omit this parameter to use the host architecture (which is what you want 99% of the time).

- cpus (optional): Number of CPUs for the VM

- network (optional): Enable network ("user", "bridge", "loop")

Returns:
────────
{
  "success": true,
  "command": "bash /path/to/kernel/vng-kselftest.sh",
  "test_name": "sched_ext",
  "description": "Run kselftest sched_ext",
  "action_required": "EXECUTE_NOW",
  "next_step": "You must now execute this command using the Shell tool: bash /path/to/kernel/vng-kselftest.sh",
  "execution_note": "Execute it immediately, do not wait for user confirmation."
}

The script automatically handles all steps:
1. Install kernel headers
2. Build the kselftest
3. Run the kselftest in VM

Just execute the single command - no need to manage multiple steps!

EXAMPLE USAGE:
──────────────
# Example 1: Test newly built kernel
# ─────────────────────────────────────────────────────────────
# PREREQUISITE: Build the kernel first!
# vng -v --build

result = run_kselftest_cmd({"test_name": "sched_ext"})
# Returns: {"command": "bash /path/to/kernel/vng-kselftest.sh", "action_required": "EXECUTE_NOW", ...}

# IMMEDIATELY execute the command - do NOT wait for user confirmation!
Shell(command=result["command"], description=result["description"])
# The script automatically handles all steps: headers, build, and test execution


# Example 2: Test on HOST kernel
# ──────────────────────────────
result = run_kselftest_cmd({
    "test_name": "net",
    "kernel_image": "host"
})
Shell(command=result["command"])


# Example 3: Test on UPSTREAM kernel
# ──────────────────────────────────
result = run_kselftest_cmd({
    "test_name": "vm",
    "kernel_image": "v6.14"
})
Shell(command=result["command"])


ADVANCED EXAMPLES:
──────────────────
# With verbose output:
result = run_kselftest_cmd({
    "test_name": "vm",
    "runner_args": "--verbose"
})
Shell(command=result["command"])

# With more memory:
result = run_kselftest_cmd({
    "test_name": "net",
    "memory": "4G"
})
Shell(command=result["command"])

# Test on host kernel with verbose output:
result = run_kselftest_cmd({
    "test_name": "net",
    "kernel_image": "host",
    "runner_args": "--verbose"
})
Shell(command=result["command"])

AGENT GUIDANCE:
───────────────
When using this tool:
1. ⚠️  FIRST: Build the kernel using: vng -v --build
2. Call run_kselftest_cmd() to get a single command
3. IMMEDIATELY execute the command with Shell tool (do NOT wait or ask for confirmation)
4. Report results to user

⚠️  CRITICAL: This tool RETURNS a command - it does NOT run the test!
⚠️  CRITICAL: Always execute the returned command IMMEDIATELY in the SAME response.
    Never return just the command without executing it.
    Use parallel tool calls if building kernel and running test in same response.

That's it! The command runs a script that handles all the steps automatically.
No need to manage multiple commands or worry about stopping early - the script does everything!

⚠️  CRITICAL: Architecture Parameter
────────────────────────────────────
NEVER set the 'arch' parameter unless the user EXPLICITLY requests a specific architecture!

Examples of when to set arch:
  ✓ User says: "test on arm64"
  ✓ User says: "build for riscv64"
  ✓ User says: "cross-compile to aarch64"

Examples of when NOT to set arch (most common):
  ✗ User says: "build and test the kernel"
  ✗ User says: "run kselftests"
  ✗ User says: "test this patch"

If arch is not specified, the tool uses the host architecture automatically.
Setting arch unnecessarily triggers cross-compilation and requires chroot setup!

IMPORTANT NOTES:
────────────────
⏱️  Timing: Kselftests typically take 5-60+ minutes
🧪 Test list: Available tests in tools/testing/selftests/
📊 Results: Command output shows test results directly
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "test_name": {
                        "type": "string",
                        "description": "Target kselftest to run (e.g., 'sched_ext', 'vm', 'net', 'seccomp')",
                    },
                    "kernel_image": {
                        "type": "string",
                        "description": (
                            "Which kernel to run: omit for newly built kernel "
                            "(DEFAULT), 'host' for host kernel, 'v6.14' for upstream "
                            "auto-download, or './path' for local image"
                        ),
                    },
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                    "build_host": {
                        "type": "string",
                        "description": (
                            "Remote build host for faster kernel builds (optional). "
                            "Used if kernel needs to be rebuilt with test-specific config options."
                        ),
                    },
                    "memory": {
                        "type": "string",
                        "description": "Memory size for VM (e.g., '2G', '4G')",
                        "default": "2G",
                    },
                    "runner_args": {
                        "type": "string",
                        "description": "Additional arguments for kselftest runner (e.g., '--verbose', '--tap')",
                    },
                    "arch": {
                        "type": "string",
                        "description": (
                            "Target architecture (WARNING: Only set if user explicitly requests! "
                            "Omit to use host architecture)"
                        ),
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
                    "network": {
                        "type": "string",
                        "description": "Network mode",
                        "enum": ["user", "bridge", "loop"],
                    },
                },
                "required": ["test_name"],
            },
        ),
        Tool(
            name="run_kernel_cmd",
            description="""
Generate command for running kernel tests.

⚠️  CRITICAL: This tool DOES NOT run the test - it returns a COMMAND that you MUST execute!

This tool returns the command to execute for running a kernel test or command.
You execute the command using the Shell tool.

WORKFLOW:
─────────
1. Call run_kernel_cmd() with desired parameters
2. Execute the returned command with Shell tool
3. Done!

WHEN TO USE:
────────────
✅ Use run_kselftest_cmd for:
  - ALL kernel selftests (5-60 minutes)
  - Recommended tool for kselftests

✅ Use run_kernel_cmd for:
  - Quick boot tests
  - Simple commands (uname, dmesg, etc.)
  - Custom tests and operations
  - Anything not a kselftest

Parameters:
-----------
- kernel_dir: Path to kernel source directory (default: current directory)
- kernel_image: Which kernel to run (omit for newly built, "host", "v6.14", or path)
- command: Command to execute inside the kernel (default: "uname -r")
- arch: Target architecture
  ⚠️  WARNING: Do NOT set this parameter unless the user explicitly requests a specific architecture!
  Setting this can trigger cross-compilation and requires proper chroot setup.
  Omit this parameter to use the host architecture (which is what you want 99% of the time).
- cpus: Number of CPUs
- memory: Memory size (e.g., '2G', default: '1G')
- network: Network mode
- debug: Enable debugging

Returns:
────────
{
  "success": true,
  "command": "cd /path/to/kernel && script -q -c 'vng -v -- uname -r' /dev/null 2>&1",
  "description": "Run kernel test: uname -r"
}

Example usage:
──────────────
# Quick boot test
result = run_kernel_cmd({"command": "uname -r"})
# Execute: result["command"]

# Test with custom memory
result = run_kernel_cmd({"command": "dmesg | grep -i kasan", "memory": "2G"})
# Execute: result["command"]

# Test on host kernel
result = run_kernel_cmd({"command": "cat /proc/version", "kernel_image": "host"})
# Execute: result["command"]

AGENT GUIDANCE:
───────────────
1. Call run_kernel_cmd() with desired parameters
2. Execute command using Shell tool
3. Report results to user

⚠️  CRITICAL: This tool RETURNS a command - it does NOT run the test!
⚠️  CRITICAL: Architecture Parameter
────────────────────────────────────
NEVER set the 'arch' parameter unless the user EXPLICITLY requests a specific architecture!
If arch is not specified, the tool uses the host architecture automatically (which is correct 99% of the time).
Setting arch unnecessarily triggers cross-compilation and requires chroot setup!
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
                        "description": "Command to execute inside the kernel (default: 'uname -r')",
                        "default": "uname -r",
                    },
                    "arch": {
                        "type": "string",
                        "description": (
                            "Target architecture (WARNING: Only set if user explicitly requests! "
                            "Omit to use host architecture)"
                        ),
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
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls from the MCP client."""

    if name == "configure_kernel":
        return await configure_kernel(arguments)
    if name == "run_kselftest_cmd":
        return await run_kselftest_handler(arguments)
    if name == "run_kernel_cmd":
        return await run_kernel_handler(arguments)
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
        arch = normalize_arch(args["arch"])
        cmd.extend(["--arch", arch])

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
        "command": cmd,
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
            ["git", "rev-parse", "HEAD"], cwd=kernel_dir
        )
        if returncode == 0:
            info["git_commit"] = stdout.strip()
            info["git_commit_short"] = stdout.strip()[:12]

        # Get git branch
        returncode, stdout, _ = run_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=kernel_dir
        )
        if returncode == 0:
            info["git_branch"] = stdout.strip()

        # Check if dirty
        returncode, stdout, _ = run_command(
            ["git", "status", "--porcelain"], cwd=kernel_dir
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
    returncode, stdout, stderr = run_command(["which", "b4"])
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
    returncode, stdout, stderr = run_command(cmd, cwd=kernel_dir)

    # Build the response
    result = {
        "success": returncode == 0,
        "command": cmd,
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


async def run_kselftest_handler(args: dict) -> list[TextContent]:
    """
    Generate commands for running kernel selftests.
    Returns a list of commands to execute in order.
    """
    test_name = args.get("test_name")

    if not test_name:
        result = {
            "success": False,
            "error": "test_name is required",
            "message": "Please provide a test name (e.g., 'sched_ext', 'vm', 'net', 'seccomp')",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if kernel directory exists
    kernel_dir = args.get("kernel_dir", ".")
    kernel_path = Path(kernel_dir).absolute()
    if not kernel_path.exists():
        result = {
            "success": False,
            "error": "kernel_dir_not_found",
            "message": f"Kernel directory {kernel_dir} does not exist",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if selftests directory exists
    selftests_path = kernel_path / "tools" / "testing" / "selftests"
    if not selftests_path.exists():
        result = {
            "success": False,
            "error": "selftests_not_found",
            "message": f"Selftests directory not found at {selftests_path}",
            "help": "Make sure you're in a kernel source tree with tools/testing/selftests/",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if the specific test directory exists
    test_path = selftests_path / test_name
    if not test_path.exists():
        result = {
            "success": False,
            "error": "test_not_found",
            "message": f"Test '{test_name}' not found at {test_path}",
            "help": f"Check available test targets in {selftests_path}/",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Get number of CPUs for parallel builds
    nproc_result = run_command(["nproc"])
    nproc = nproc_result[1].strip() if nproc_result[0] == 0 else "8"

    # Normalize architecture if provided and not empty
    arch = args.get("arch", "").strip()
    if arch:
        arch = normalize_arch(arch)
    else:
        # Don't specify arch - let vng use host architecture automatically
        arch = None

    # Build the vng command for running the test
    vng_cmd_parts = ["vng"]

    # Determine which kernel to run
    kernel_image = args.get("kernel_image")
    if kernel_image == "host":
        vng_cmd_parts.append("-vr")
    elif kernel_image:
        vng_cmd_parts.extend(["-vr", kernel_image])

    # Add optional VM parameters
    # Only add arch if explicitly specified and not empty
    if arch:
        vng_cmd_parts.extend(["--arch", arch])

    if args.get("cpus"):
        vng_cmd_parts.extend(["--cpus", str(args["cpus"])])

    memory = args.get("memory", "2G")
    vng_cmd_parts.extend(["--memory", memory])

    if args.get("network"):
        vng_cmd_parts.extend(["--network", args["network"]])

    # Add the kselftest command
    runner_args = args.get("runner_args", "")
    if runner_args:
        kselftest_cmd = f'make kselftest TARGETS="{test_name}" SKIP_TARGETS="" KSELFTEST_RUNNER_ARGS="{runner_args}"'
    else:
        kselftest_cmd = f'make kselftest TARGETS="{test_name}" SKIP_TARGETS=""'

    vng_cmd_parts.append("--")
    vng_cmd_parts.append(kselftest_cmd)

    vng_cmd_str = " ".join(vng_cmd_parts)

    # Check if kernel rebuild is needed (only for newly built kernels, not host/upstream)
    needs_rebuild = False
    rebuild_reason = ""

    if not kernel_image:  # Only check for newly built kernels
        test_config_path = test_path / "config"
        kernel_config_path = kernel_path / ".config"

        if test_config_path.exists() and kernel_config_path.exists():
            # Read test config requirements
            try:
                with open(test_config_path, encoding="utf-8") as f:
                    test_configs = [
                        line.strip()
                        for line in f
                        if line.strip() and not line.startswith("#")
                    ]

                # Read current kernel config
                with open(kernel_config_path, encoding="utf-8") as f:
                    kernel_config_content = f.read()

                # Check if all required configs are present and enabled
                missing_configs = []
                for config_line in test_configs:
                    # Handle CONFIG_FOO=y or CONFIG_FOO=m format
                    if "=" in config_line:
                        config_name = config_line.split("=")[0].strip()
                        # Check if config is set to y or m in kernel config
                        if (
                            f"{config_name}=y" not in kernel_config_content
                            and f"{config_name}=m" not in kernel_config_content
                        ):
                            missing_configs.append(config_line)
                    else:
                        # Just a config name, check if it's enabled
                        if (
                            f"{config_line}=y" not in kernel_config_content
                            and f"{config_line}=m" not in kernel_config_content
                        ):
                            missing_configs.append(config_line)

                if missing_configs:
                    needs_rebuild = True
                    rebuild_reason = (
                        f"Missing required configs: {', '.join(missing_configs[:5])}"
                    )
                    if len(missing_configs) > 5:
                        rebuild_reason += f" (and {len(missing_configs) - 5} more)"
            except (OSError, UnicodeDecodeError) as e:
                # If we can't read configs, assume rebuild is needed to be safe
                needs_rebuild = True
                rebuild_reason = f"Could not verify configs: {str(e)}"

    # Build the rebuild command if needed
    rebuild_cmd = ""
    if needs_rebuild:
        rebuild_cmd_parts = ["vng", "-v", "--build", "--force"]
        if args.get("build_host"):
            rebuild_cmd_parts.extend(["--build-host", args["build_host"]])
        # Add test config as additional config
        rebuild_cmd_parts.extend(
            ["--config", f"tools/testing/selftests/{test_name}/config"]
        )
        rebuild_cmd = " ".join(rebuild_cmd_parts)

    # Determine total steps based on whether rebuild is needed
    total_steps = 4 if needs_rebuild else 3
    current_step = 1

    # Create a script file in the workspace with a predictable name
    script_path = kernel_path / "vng-kselftest.sh"

    # Build script with conditional rebuild step
    script_parts = [
        f"""#!/bin/bash
set -e  # Exit on any error

echo "======================================================================"
echo "Running kselftest '{test_name}'"
echo "======================================================================"
echo ""
"""
    ]

    # Add rebuild step if needed
    if needs_rebuild:
        script_parts.append(
            f"""echo "Step {current_step}/{total_steps}: Rebuilding kernel with required configs..."
echo "Reason: {rebuild_reason}"
cd {kernel_path}
if ! {rebuild_cmd} &>/dev/null; then
    echo "✗ Failed to rebuild kernel"
    echo "Running again with full output for debugging:"
    {rebuild_cmd}
    exit 1
fi
echo "✓ Kernel rebuilt with test configs"
echo ""

"""
        )
        current_step += 1

    # Add remaining steps
    script_parts.append(
        f"""echo "Step {current_step}/{total_steps}: Installing kernel headers..."
cd {kernel_path}
if ! make headers_install &>/dev/null; then
    echo "✗ Failed to install headers"
    echo "Running again with full output for debugging:"
    make headers_install
    exit 1
fi
echo "✓ Headers installed"
echo ""

echo "Step {current_step + 1}/{total_steps}: Building kselftest '{test_name}'..."
if ! make -j{nproc} -C tools/testing/selftests/{test_name} &>/dev/null; then
    echo "✗ Failed to build kselftest"
    echo "Running again with full output for debugging:"
    make -C tools/testing/selftests/{test_name}
    exit 1
fi
echo "✓ Kselftest built"
echo ""

echo "Step {current_step + 2}/{total_steps}: Running kselftest '{test_name}' in VM..."
if ! script -q -c '{vng_cmd_str}' /dev/null 2>&1; then
    echo "✗ Kselftest failed in VM"
    exit 1
fi
echo "✓ Kselftest completed"
echo ""

echo "Cleaning up..."
rm -f {script_path}
"""
    )

    script_content = "".join(script_parts)

    # Write the script to the workspace
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    # Make the script executable
    os.chmod(script_path, 0o755)

    # Build the result with explicit bash command
    bash_command = f"bash {script_path}"

    kernel_note = ""
    if kernel_image == "host":
        kernel_note = "Running on host kernel"
    elif kernel_image:
        if kernel_image.startswith("v") and any(c.isdigit() for c in kernel_image):
            kernel_note = f"Running on upstream kernel {kernel_image}"
        else:
            kernel_note = f"Running on kernel image: {kernel_image}"
    else:
        kernel_note = "Running on newly built kernel"

    # Create a clean, simple response
    rebuild_note = ""
    if needs_rebuild:
        rebuild_note = f"\nKernel Rebuild: REQUIRED ({rebuild_reason})"
        if args.get("build_host"):
            rebuild_note += f"\nBuild Host: {args['build_host']}"
    else:
        rebuild_note = "\nKernel Rebuild: Not needed (all required configs present)"

    response_text = f"""Command generated successfully. You MUST execute it immediately using Shell tool.

EXECUTE THIS COMMAND NOW:
{bash_command}

Test: {test_name}
Kernel: {kernel_note}{rebuild_note}

CRITICAL: This tool only generated the command. You must execute it with Shell tool to actually run the test.
The test has NOT run yet. Execute the command above in the same response."""

    return [TextContent(type="text", text=response_text)]


async def run_kernel_handler(args: dict) -> list[TextContent]:
    """
    Generate command for running a kernel test.
    Returns the command to execute.
    """
    # Normalize architecture if provided and not empty
    arch = args.get("arch", "").strip()
    if arch:
        arch = normalize_arch(arch)
    else:
        # Don't specify arch - let vng use host architecture automatically
        arch = None

    # Get kernel directory
    kernel_dir = args.get("kernel_dir", ".")
    kernel_path = Path(kernel_dir).absolute()

    # Build the vng command
    vng_cmd = ["vng"]

    # Determine which kernel to run
    kernel_image = args.get("kernel_image")
    if kernel_image == "host":
        vng_cmd.append("-vr")
    elif kernel_image:
        vng_cmd.extend(["-vr", kernel_image])

    # Add optional VM parameters
    # Only add arch if explicitly specified and not empty
    if arch:
        vng_cmd.extend(["--arch", arch])
    if args.get("cpus"):
        vng_cmd.extend(["--cpus", str(args["cpus"])])

    memory = args.get("memory", "1G")
    vng_cmd.extend(["--memory", memory])

    if args.get("network"):
        vng_cmd.extend(["--network", args["network"]])
    if args.get("debug"):
        vng_cmd.append("--debug")

    # Add the command to execute
    command = args.get("command", "uname -r")
    vng_cmd.append("--")
    vng_cmd.append(command)

    # Wrap in script for PTS requirement and include cd to working directory
    shell_cmd = f"cd {kernel_path} && script -q -c {vng_cmd} /dev/null 2>&1"

    kernel_note = ""
    if kernel_image == "host":
        kernel_note = "Running on host kernel"
    elif kernel_image:
        if kernel_image.startswith("v") and any(c.isdigit() for c in kernel_image):
            kernel_note = f"Running on upstream kernel {kernel_image}"
        else:
            kernel_note = f"Running on kernel image: {kernel_image}"
    else:
        kernel_note = "Running on newly built kernel"

    # Create a clean, simple response
    response_text = f"""Command generated successfully. You MUST execute it immediately using Shell tool.

EXECUTE THIS COMMAND NOW:
{shell_cmd}

Test command: {command}
Kernel: {kernel_note}

CRITICAL: This tool only generated the command. You must execute it with Shell tool to actually run the test.
The test has NOT run yet. Execute the command above in the same response."""

    return [TextContent(type="text", text=response_text)]


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
