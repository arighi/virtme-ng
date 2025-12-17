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

   ⚠️  ALWAYS use sufficient timeout for builds
   ⚠️  For faster builds, use remote hosts with --build-host option

   Default shell command timeouts (30 seconds) are TOO SHORT and WILL FAIL!

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
    # STEP 1: BUILD
    vng -v --build --configitem CONFIG_KASAN=y

     # STEP 2: TEST (run_kernel tool or shell command)
     script -q -c "vng -- dmesg | grep -i kasan" /dev/null 2>&1

     Example 2: Remote build + local test
     ─────────────────────────────────────
    # STEP 1: BUILD on remote host
    vng -v --build --build-host builder

     # STEP 2: TEST locally (run_kernel tool or shell command)
     script -q -c "vng -- uname -r" /dev/null 2>&1

    Example 3: Remote build with config + test
    ───────────────────────────────────────────
    # STEP 1: BUILD on remote host
    vng -v --build --build-host myserver --configitem CONFIG_DEBUG_INFO=y

    # STEP 2: TEST (run_kernel tool or shell command)
    script -q -c "vng -- cat /proc/version" /dev/null 2>&1

5. Running Kernel Selftests (kselftests)
   ======================================

   WORKFLOW FOR AI AGENTS - How to run kselftests with virtme-ng:
   ──────────────────────────────────────────────────────────────

   ⚠️  IMPORTANT: Build the kernel FIRST!
   vng -v --build

   Then run_kselftest command handles the rest:
   1. Builds the kselftest (if needed)
   2. Runs the kselftest asynchronously
   3. Returns job_id for polling

   BASIC USAGE
   ───────────
   # Start the kselftest asynchronously
   result = run_kselftest({"test_name": "sched_ext"})

   # Poll for results every 10 sec
   status = get_job_status({"job_id": result["job_id"]})

   The command automatically:
   - Checks if kernel is built (builds it if needed)
   - Checks if kselftest is built (builds it if needed)
   - Runs the kselftest asynchronously (no MCP timeout)
   - Sets appropriate defaults (2G memory, 1 hour timeout)
   - Returns a job_id for polling progress

   ⏱️ TIMEOUT REQUIREMENTS:
   ────────────────────────
  - Kselftests can take 10+ minutes depending on the test suite
  - Builds can take 5-10 minutes (handled automatically, 10 min timeout)
  - run_kselftest sets default timeout to 3600 seconds (1 hour)
   - Can be customized with timeout parameter if needed

   COMPLETE EXAMPLES:
   ──────────────────

   Example 1: Run sched_ext tests
   ──────────────────────────────
   # STEP 1: Build kernel first!
   vng -v --build

   # STEP 2: Start the kselftest asynchronously
   result = run_kselftest({"test_name": "sched_ext"})

   # STEP 3: Poll for results every 10 sec
   status = get_job_status({"job_id": result["job_id"]})
   # Repeat until status is "completed" or "failed"

   # Note: run_kselftest automatically builds the kselftest if needed!

   Example 2: Run VM tests with verbose output
   ────────────────────────────────────────────
   # PREREQUISITE: Build kernel first (if testing newly built kernel)
   vng -v --build

   # Run kselftest with options
   result = run_kselftest({
       "test_name": "vm",
       "runner_args": "--verbose"
   })

   # Poll for results
   status = get_job_status({"job_id": result["job_id"]})

   Example 3: Run tests on HOST kernel
   ────────────────────────────────────
   # One command - automatically builds kselftest only
   result = run_kselftest({
       "test_name": "net",
       "kernel_image": "host"
   })

   # Poll for results
   status = get_job_status({"job_id": result["job_id"]})

   Example 4: Run tests on UPSTREAM kernel
   ────────────────────────────────────────
   # One command - automatically builds kselftest, downloads kernel
   result = run_kselftest({
       "test_name": "seccomp",
       "kernel_image": "v6.14"
   })

   # Poll for results
   status = get_job_status({"job_id": result["job_id"]})

   Example 5: Run tests with custom settings
   ──────────────────────────────────────────
   # PREREQUISITE: Build kernel first
   vng -v --build

   result = run_kselftest({
       "test_name": "vm",
       "memory": "4G",
       "timeout": 7200,  # 2 hours for test
       "runner_args": "--verbose"
   })

6. MCP Tools Available
   --------------------
   This MCP server provides:
   - configure_kernel: Generate/modify kernel .config
   - run_kernel: Run and test kernels in QEMU (synchronous)
   - run_kselftest: Run kernel selftests asynchronously (RECOMMENDED for kselftests)
   - run_kernel_async: Run kernel tests asynchronously (for custom long tests)
   - get_job_status: Check status of async jobs
   - cancel_job: Cancel running async jobs
   - list_jobs: List all active async jobs
   - get_kernel_info: Get info about kernel source directory
   - apply_patch: Apply patches from lore.kernel.org
   - verify_kernel: Verify a commit by building and booting it

   For building kernels, use shell commands with 'vng -v --build' as documented above.
   For running kselftests, use the run_kselftest command (see section 5).
   For validating patch series, see section 7 below.

7. Validating Patch Series
   ========================================================

   When a user asks to validate a patch series by building and booting each commit,
   use the verify_kernel tool for each commit in the series.

   ⚠️  CRITICAL: ALWAYS BUILD **AND** BOOT EACH KERNEL
   ════════════════════════════════════════════════════
   - Building alone is NOT sufficient validation
   - EVERY kernel MUST be booted and tested inside virtme-ng
   - A kernel that builds but doesn't boot is a FAILED commit
   - NEVER skip the boot testing step

   ⚠️  WARNING: This operation can take HOURS (10-60+ minutes per commit)

   RECOMMENDED WORKFLOW: Use verify_kernel for Each Commit
   ────────────────────────────────────────────────────────

   The verify_kernel tool validates a single commit by building and booting it.
   For patch series, call verify_kernel multiple times - once for each commit.

   STEP-BY-STEP WORKFLOW:
   ──────────────────────

   Step 1: Get the list of commits
   git rev-list --reverse START_COMMIT^..END_COMMIT

   This returns a list of commit SHAs, one per line.

   Step 2: Save current git state
   git rev-parse HEAD

   Save this to restore later.

   Step 3: For each commit, call verify_kernel
   ───────────────────────────────────────────

   Basic verification:
   verify_kernel({
       "commit": "abc1234",
   })

   With remote build host (faster):
   verify_kernel({
       "commit": "abc1234",
       "build_host": "builder",
   })

   With custom config:
   verify_kernel({
       "commit": "abc1234",
       "config_items": ["CONFIG_KASAN=y"],
   })

   With custom test:
   verify_kernel({
       "commit": "abc1234",
       "test_command": "dmesg | grep -i error || echo 'No errors'",
   })

   Step 4: Restore original git state
   git checkout ORIGINAL_SHA

   Step 5: Report results
   Summarize which commits passed/failed with a clear table or list.

   EXAMPLE INTERACTION:
   ────────────────────

   User: "Validate that each commit between HEAD~3 and HEAD builds and boots"

   AI should do:
   1. Get commits: git rev-list --reverse HEAD~3^..HEAD
   2. Save current: git rev-parse HEAD
   3. For EACH commit:
      result = verify_kernel({"commit": "<sha>"})
      Record: commit passed/failed based on result["success"]
   4. Restore: git checkout <original>
   5. Report: "Validated 4 commits: 3 passed (build+boot), 1 failed"

   EXAMPLE WITH REMOTE BUILD:
   ──────────────────────────

   User: "Validate HEAD~5 to HEAD using my build server 'builder'"

   For each commit:
   verify_kernel({
       "commit": "<sha>",
       "build_host": "builder",
   })

   EXAMPLE WITH CUSTOM TEST:
   ─────────────────────────

   User: "Validate these commits by running dmesg checks"

   For each commit:
   verify_kernel({
       "commit": "<sha>",
       "test_command": "dmesg | grep -i error || echo 'No errors found'",
   })

   EXAMPLE WITH STOP ON FAILURE:
   ──────────────────────────────

   User: "Find which commit breaks the kernel between HEAD~20 and HEAD"

   For each commit:
   result = verify_kernel({"commit": "<sha>"})
   if not result["success"]:
       report "First failing commit: <sha>" and stop

   WHY USE verify_kernel INSTEAD OF MANUAL BUILD+BOOT:
   ───────────────────────────────────────────────────

   The verify_kernel tool:
   ✅ Automatically performs BOTH build AND boot testing
   ✅ Cannot skip boot testing - it's enforced by the tool
   ✅ Returns structured results with both build and boot status
   ✅ Handles errors and timeouts gracefully
   ✅ Reports clear success/failure status
   ✅ More reliable than manual orchestration

   CRITICAL RULES FOR AI AGENTS:
   ─────────────────────────────
   ⚠️  MANDATORY: Use verify_kernel for each commit
       - The tool automatically boots every successfully built kernel
       - You cannot skip this step - it's built into verify_kernel
       - A kernel that builds but doesn't boot is reported as FAILED

   - Always save and restore the original git state
   - Use proper timeouts: 10s for git commands
   - For faster builds, pass build_host if user mentions a build server
   - Show progress to the user after each commit
   - Provide a clear summary showing BOTH build and boot results
   - Handle failures gracefully - continue validation unless user wants to stop

   IMPORTANT NOTES:
   ────────────────
   ⚠️  MOST IMPORTANT: verify_kernel enforces boot testing
       - Every call to verify_kernel boots the kernel if build succeeds
       - This is NOT optional - it's built into the tool
       - result["success"] is true only if BOTH build AND boot succeed

  - Always use timeout=600 (10 min) for builds (handled by verify_kernel)
  - Always use timeout=300 (5 min) for boots (handled by verify_kernel)
   - Each commit needs a full rebuild (10-60+ minutes per commit)
   - Remote builds (--build-host) are much faster for patch series validation
   - Always restore the original git state, even if validation fails
   - Report results clearly: "Build OK, Boot OK" or "Build FAILED" or "Build OK, Boot FAILED"

   MANDATORY WORKFLOW:
   ───────────────────
   For each commit in the range, you MUST perform ALL these steps:
   1. Checkout the commit using git
   2. BUILD the kernel using: vng -v --build
   3. BOOT the kernel using run_kernel() - THIS STEP IS MANDATORY
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

      MINIMUM (always required): Verify kernel boots
      run_kernel({"command": "uname -r"})

      OR with custom test command (if user specified):
      run_kernel({"command": "user_test_command_here"})

      OR using shell command:
      script -q -c 'vng -- uname -r' /dev/null 2>&1

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
      - If build succeeds, BOOT (MANDATORY): run_kernel({"command": "uname -r"})
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
       - ALWAYS run run_kernel() after successful build
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
   3. If build succeeds: run_kernel({"command": "uname -r"})  ⚠️ MANDATORY
   4. Record both build and boot results

   EXAMPLE WITH CUSTOM TEST:
   ─────────────────────────

   User: "Validate these commits by running dmesg checks"

   For each commit:
   1. git checkout COMMIT
   2. vng -v --build
   3. If build succeeds: run_kernel({"command": "dmesg | grep -i error || echo 'No errors found'"})  ⚠️ MANDATORY
   4. Record both build and boot/test results

   EXAMPLE WITH STOP ON FAILURE:
   ──────────────────────────────

   User: "Find which commit breaks the kernel between HEAD~20 and HEAD"

   For each commit:
   1. Build kernel: vng -v --build
   2. If build fails: report "First failing commit (build): COMMIT_SHA" and stop
   3. If build succeeds: Boot kernel: run_kernel({"command": "uname -r"})  ⚠️ MANDATORY
   4. If boot fails: report "First failing commit (boot): COMMIT_SHA" and stop
   5. If both succeed: continue to next commit

   IMPORTANT NOTES:
   ────────────────
   ⚠️  MOST IMPORTANT: ALWAYS test boot after every successful build
       - This is NOT optional - it's a required validation step
       - Use run_kernel({"command": "uname -r"}) at minimum
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
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
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


# ============================================================================
# Async Job Management Infrastructure
# ============================================================================

# Global job storage (jobs persist across tool calls)
_active_jobs = {}
_jobs_lock = threading.Lock()


@dataclass
class Job:
    """Represents an async kernel test job."""

    job_id: str
    command: str
    args: dict
    status: str = "starting"  # starting, running, completed, failed, cancelled
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    def to_dict(self) -> dict:
        """Convert job to dictionary for JSON serialization."""
        result = {
            "job_id": self.job_id,
            "status": self.status,
            "command": self.command,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "elapsed_seconds": round(self.elapsed_seconds(), 2),
        }

        if self.status in ("completed", "failed"):
            result["end_time"] = datetime.fromtimestamp(self.end_time).isoformat()
            result["returncode"] = self.returncode
            result["total_time_seconds"] = round(self.elapsed_seconds(), 2)

            # Include output (truncate if too large for MCP response)
            max_output = 50000  # 50KB max per field
            if len(self.stdout) > max_output:
                result["stdout"] = self.stdout[-max_output:]
                result["stdout_truncated"] = True
                result["stdout_note"] = (
                    f"Output truncated (showing last {max_output} chars of {len(self.stdout)})"
                )
            else:
                result["stdout"] = self.stdout
                result["stdout_truncated"] = False

            if self.stderr:
                if len(self.stderr) > max_output:
                    result["stderr"] = self.stderr[-max_output:]
                    result["stderr_truncated"] = True
                    result["stderr_note"] = (
                        f"Output truncated (showing last {max_output} chars of {len(self.stderr)})"
                    )
                else:
                    result["stderr"] = self.stderr
                    result["stderr_truncated"] = False

        if self.error:
            result["error"] = self.error

        return result


def _run_job_in_background(job_id: str):
    """
    Run a kernel test job in the background thread.
    This is the worker function that actually executes the vng command.
    """
    with _jobs_lock:
        if job_id not in _active_jobs:
            return
        job = _active_jobs[job_id]

    try:
        # Update status to running
        job.status = "running"

        # Build the vng command (same as sync run_kernel)
        kernel_dir = job.args.get("kernel_dir", ".")
        vng_cmd = ["vng"]

        # Determine which kernel to run
        kernel_image = job.args.get("kernel_image")
        if kernel_image == "host":
            vng_cmd.append("-vr")
        elif kernel_image:
            vng_cmd.extend(["-vr", kernel_image])

        if job.args.get("arch"):
            vng_cmd.extend(["--arch", job.args["arch"]])
        if job.args.get("cpus"):
            vng_cmd.extend(["--cpus", str(job.args["cpus"])])
        if job.args.get("memory"):
            vng_cmd.extend(["--memory", job.args["memory"]])
        if job.args.get("network"):
            vng_cmd.extend(["--network", job.args["network"]])
        if job.args.get("debug"):
            vng_cmd.append("--debug")

        if job.args.get("command"):
            vng_cmd.append("--")
            vng_cmd.append(job.args["command"])

        # Wrap in script for PTS requirement
        vng_cmd_str = shlex.join(vng_cmd)
        shell_cmd = f"script -q -c {shlex.quote(vng_cmd_str)} /dev/null 2>&1"

        # Execute the command
        timeout = job.args.get("timeout", 3600)
        returncode, stdout, stderr = run_command(
            ["sh", "-c", shell_cmd], cwd=kernel_dir, timeout=timeout
        )

        # Update job with results
        job.returncode = returncode
        job.stdout = stdout
        job.stderr = stderr
        job.status = "completed" if returncode == 0 else "failed"
        job.end_time = time.time()

    except Exception as e:  # pylint: disable=broad-exception-caught
        job.status = "failed"
        job.error = str(e)
        job.end_time = time.time()


def _wait_for_job_completion(job_id: str, max_wait_seconds: int = 60) -> Job:
    """
    Wait for a job to complete, polling its status periodically.
    Returns the job object after waiting up to max_wait_seconds.

    Args:
        job_id: The job ID to wait for
        max_wait_seconds: Maximum time to wait in seconds (default: 60)

    Returns:
        The job object (may or may not be completed)
    """
    start_time = time.time()
    poll_interval = 2  # Poll every 2 seconds

    while time.time() - start_time < max_wait_seconds:
        with _jobs_lock:
            if job_id not in _active_jobs:
                # Job disappeared, return None or handle error
                break
            job = _active_jobs[job_id]

            # Check if job completed
            if job.status in ("completed", "failed", "cancelled"):
                return job

        # Wait before next poll
        time.sleep(poll_interval)

    # Return job even if not completed (max wait time exceeded)
    with _jobs_lock:
        if job_id in _active_jobs:
            return _active_jobs[job_id]

    return None


def _cleanup_old_jobs(max_age_hours: int = 24):
    """
    Clean up jobs older than max_age_hours.
    Called automatically when listing/checking jobs.
    """
    cutoff = time.time() - (max_age_hours * 3600)

    with _jobs_lock:
        for job_id in list(_active_jobs.keys()):
            job = _active_jobs[job_id]
            if job.end_time and job.end_time < cutoff:
                del _active_jobs[job_id]


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

   ⏱️  CRITICAL: Builds take 10-60+ minutes! Use sufficient timeout.

   • For local builds:
     vng -v --build

   • For REMOTE builds (when user specifies a build server/host):
     vng -v --build --build-host <hostname>

     Examples of when to use --build-host:
     - User says: "build on my server called 'builder'"
     - User says: "compile on remote host 'myserver'"
     - User says: "use the build machine to compile"
     - User says: "build this on <hostname>"

   • With custom config:
     vng -v --build --configitem CONFIG_DEBUG_INFO=y

   • Remote build with custom config:
     vng -v --build --build-host builder --configitem CONFIG_KASAN=y

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
        Tool(
            name="verify_kernel",
            description="""
Verify a kernel commit by building and booting it.
This tool validates that a specific commit both compiles and runs correctly.

⚠️  CRITICAL: This tool validates BOTH build AND boot!
════════════════════════════════════════════════════════
- Building alone is NOT sufficient validation
- The kernel MUST be booted and tested inside virtme-ng
- A kernel that builds but doesn't boot is considered FAILED
- This operation takes 10-60+ minutes per commit

WHAT THIS TOOL DOES:
═══════════════════════════════════════════════════════════════════════════
1. Optionally checks out the specified commit (if commit parameter provided)
2. BUILDS the kernel using vng --build
3. If build succeeds: BOOTS the kernel using vng -- test_command
4. Returns BOTH build and boot results

A commit is considered PASSED only if BOTH build AND boot succeed.

Parameters:
───────────
- commit: Git commit to verify (optional)
  Default: None (verify current HEAD without checkout)
  Examples: "HEAD~3", "abc1234", "v6.8"
  If provided, the tool will checkout this commit before building

- kernel_dir: Path to kernel source directory
  Default: current directory

- build_host: Remote build host for faster builds (optional)
  Example: "builder", "myserver.example.com"
  If specified, uses: vng --build --build-host <hostname>

- config_items: List of CONFIG_ITEM=value for custom kernel config (optional)
  Example: ["CONFIG_KASAN=y", "CONFIG_DEBUG_INFO=y"]

- test_command: Command to run when booting the kernel (optional)
  Default: "uname -r" (just verify kernel boots)
  Example: "dmesg | grep -i error || echo 'No errors'"

- build_timeout: Timeout for build in seconds (optional)
  Default: 600 (10 minutes max)

- boot_timeout: Timeout for boot test in seconds (optional)
  Default: 300 (5 minutes)

Returns:
────────
JSON object with:
- success: Overall result (true if both build and boot passed)
- commit_sha: Full commit SHA that was verified
- commit_short: Short commit SHA
- commit_subject: Commit message subject
- build_status: "SUCCESS" or "FAILED"
- build_time_seconds: Time taken to build
- build_command: Build command that was executed
- boot_status: "SUCCESS", "FAILED", or "SKIPPED" (if build failed)
- boot_time_seconds: Time taken to boot (if applicable)
- boot_command: Boot command that was executed (if applicable)
- test_command: Test command that was run
- overall_status: "PASSED" (both OK) or "FAILED"

Example Use Cases:
══════════════════

1. Verify current commit (basic):
   verify_kernel({})

2. Verify specific commit:
   verify_kernel({"commit": "HEAD~3"})

3. Verify with remote build host (faster):
   verify_kernel({
       "commit": "abc1234",
       "build_host": "builder"
   })

4. Verify with custom config and test:
   verify_kernel({
       "commit": "v6.8",
       "config_items": ["CONFIG_KASAN=y"],
       "test_command": "dmesg | grep -i kasan"
   })

VALIDATING PATCH SERIES:
════════════════════════
To validate a patch series, call this tool multiple times for each commit:

1. Get commit list: Shell("git rev-list --reverse HEAD~5^..HEAD")
2. Save current state: Shell("git rev-parse HEAD")
3. For each commit:
   - verify_kernel({"commit": "<sha>"})
   - Record result
4. Restore state: Shell("git checkout <original>")

See section 7 of the module documentation for the complete workflow.

IMPORTANT NOTES:
════════════════
⏱️  Time Requirements:
   - Takes 10-60+ minutes (build + boot)
   - Use build_host for faster builds

⚠️  Boot Testing:
   - EVERY successfully built kernel is booted
   - This is NOT optional - it's mandatory validation
   - Skipping boot testing makes validation incomplete

🔄 Git State:
   - If commit parameter is provided, it will checkout that commit
   - You should save/restore git state when validating series
   - See documentation for complete patch series workflow

CRITICAL: This tool enforces complete validation. You cannot skip the
boot testing step. The kernel is validated by BOTH building AND booting.
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "commit": {
                        "type": "string",
                        "description": "Git commit to verify (optional, e.g., 'HEAD~3', 'abc1234', 'v6.8')",
                    },
                    "kernel_dir": {
                        "type": "string",
                        "description": "Path to kernel source directory",
                        "default": ".",
                    },
                    "build_host": {
                        "type": "string",
                        "description": "Remote build host for faster builds (optional)",
                    },
                    "config_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of CONFIG_ITEM=value settings (optional)",
                    },
                    "test_command": {
                        "type": "string",
                        "description": "Command to run when booting the kernel (default: 'uname -r')",
                        "default": "uname -r",
                    },
                    "build_timeout": {
                        "type": "integer",
                        "description": "Timeout for build in seconds (default: 600)",
                        "default": 600,
                    },
                    "boot_timeout": {
                        "type": "integer",
                        "description": "Timeout for boot test in seconds (default: 300)",
                        "default": 300,
                    },
                },
            },
        ),
        Tool(
            name="run_kselftest",
            description="""
Run kernel selftests (kselftests) asynchronously with automatic build support.

🎯 KSELFTEST RUNNER - Build kernel first!
════════════════════════════════════════════════════════════
⚠️  IMPORTANT: You must build the kernel BEFORE running kselftests!
    Use: vng -v --build

This command automatically:
1. Builds the kselftest (if needed)
2. Runs the kselftest asynchronously

Just call: run_kselftest({"test_name": "sched_ext"})

WORKFLOW:
─────────
The command handles the kselftest workflow:
1. Builds the kselftest if not already built (10 minute timeout)
2. Runs the kselftest asynchronously in the VM
3. Returns immediately with job_id

It automatically:
- Builds the kselftest (if needed)
- Runs asynchronously (returns immediately with job_id)
- Executes make kselftest with proper TARGETS/SKIP_TARGETS
- Allocates appropriate memory (default: 2G)
- Sets proper timeout (default: 3600 seconds / 1 hour)

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

- timeout (optional): Maximum runtime in seconds (default: 3600 = 1 hour)
  Increase for very long test suites

- runner_args (optional): Additional arguments for kselftest runner
  Examples: "--verbose", "--tap", "--list"

- arch (optional): Target architecture to emulate

- cpus (optional): Number of CPUs for the VM

- network (optional): Enable network ("user", "bridge", "loop")

NOTE: The kselftest is built automatically with proper timeout.
      The kernel must be built separately before running kselftests.

Returns immediately with:
- job_id: Unique identifier for this job
- status: "starting"
- test_name: The test being run
- command: The actual command executed

POLLING FOR RESULTS:
────────────────────
After starting the test, use get_job_status() to check progress:

1. Call run_kselftest() → Get job_id
2. Wait 10 seconds
3. Call get_job_status({"job_id": job_id}) → Check progress
4. Repeat step 2-3 until status is "completed" or "failed"
5. Retrieve results from final get_job_status() response

EXAMPLE USAGE:
──────────────
# Example 1: Test newly built kernel
# ─────────────────────────────────────────────────────────────
# PREREQUISITE: Build the kernel first!
# vng -v --build

result = run_kselftest({
    "test_name": "sched_ext"
})
# Automatically:
# 1. Builds kselftest (if not already built)
# 2. Runs kselftest asynchronously
# Returns: {"job_id": "kselftest_sched_ext_...", "status": "starting"}

# Poll for results
status = get_job_status({"job_id": result["job_id"]})


# Example 2: Test on HOST kernel
# ──────────────────────────────
result = run_kselftest({
    "test_name": "net",
    "kernel_image": "host"
})
# Automatically:
# 1. Builds kselftest (if not already built)
# 2. Runs kselftest on host kernel


# Example 3: Test on UPSTREAM kernel
# ──────────────────────────────────
result = run_kselftest({
    "test_name": "vm",
    "kernel_image": "v6.14"
})
# Automatically:
# 1. Builds kselftest (if not already built)
# 2. Downloads upstream kernel v6.14 (if not cached)
# 3. Runs kselftest on upstream kernel


# Example 4: Test specific kernel image
# ──────────────────────────────────────
result = run_kselftest({
    "test_name": "seccomp",
    "kernel_image": "./arch/x86/boot/bzImage"
})


ADVANCED EXAMPLES:
──────────────────
# With verbose output:
run_kselftest({
    "test_name": "vm",
    "runner_args": "--verbose"
})

# With more memory and longer timeout:
run_kselftest({
    "test_name": "net",
    "memory": "4G",
    "timeout": 7200
})

# Test on host kernel with verbose output:
run_kselftest({
    "test_name": "net",
    "kernel_image": "host",
    "runner_args": "--verbose"
})

AGENT GUIDANCE:
───────────────
When using this tool:
1. ⚠️  FIRST: Build the kernel using: vng -v --build
2. Then call run_kselftest() (it will build the kselftest automatically)
3. Inform user job started
4. Poll get_job_status() every 10-30 seconds
5. Update user with progress
6. Report final results when completed

IMPORTANT NOTES:
────────────────
⏱️  Timing: Kselftests typically take 5-60+ minutes
🧪 Test list: Available tests in tools/testing/selftests/
🔄 Async: This tool always runs asynchronously (no MCP timeout)
📊 Results: Full test output available in get_job_status() stdout
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
                    "memory": {
                        "type": "string",
                        "description": "Memory size for VM (e.g., '2G', '4G')",
                        "default": "2G",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum runtime in seconds (default: 3600 = 1 hour)",
                        "default": 3600,
                    },
                    "runner_args": {
                        "type": "string",
                        "description": "Additional arguments for kselftest runner (e.g., '--verbose', '--tap')",
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
            name="run_kernel_async",
            description="""
Run a kernel test asynchronously (non-blocking).
This tool starts a kernel test in the background and returns immediately with a job ID.

⚠️  USE THIS TOOL FOR LONG-RUNNING OPERATIONS (>2 minutes)
════════════════════════════════════════════════════════════

This solves the MCP timeout problem by:
1. Starting the job immediately (returns in <1 second)
2. Allowing you to check status periodically with get_job_status()
3. Each status check is fast (<1 second), avoiding MCP timeouts

WORKFLOW:
─────────
1. Call run_kernel_async() → Get job_id
2. Wait 10-30 seconds
3. Call get_job_status(job_id) → Check progress
4. Repeat step 2-3 until status is "completed" or "failed"
5. Retrieve results from final get_job_status() response

WHEN TO USE:
────────────
✅ Use run_kselftest for:
  - ALL kernel selftests (5-60 minutes)
  - Works with newly built, host, or upstream kernels
  - This is the recommended tool for kselftests

✅ Use run_kernel_async for:
  - Custom long-running tests (>2 minutes)
  - Non-kselftest operations
  - Operations that might timeout with run_kernel

✅ Use run_kernel (sync) for:
  - Quick boot tests (<2 minutes)
  - Simple commands (uname, dmesg, etc.)

Parameters are identical to run_kernel:
- kernel_dir: Path to kernel source directory (default: current directory)
- kernel_image: Which kernel to run (omit for newly built, "host", "v6.14", or path)
- command: Command to execute inside the kernel
- arch: Target architecture
- cpus: Number of CPUs
- memory: Memory size (e.g., '2G')
- timeout: Maximum runtime in seconds (default: 3600)
- network: Network mode
- debug: Enable debugging

Returns immediately with:
- job_id: Unique identifier for this job
- status: "starting"
- command: The command being executed

Example usage:
──────────────
# Step 1: Start the test
result = run_kernel_async({
    "command": "make kselftest TARGETS='sched_ext' SKIP_TARGETS=''",
    "memory": "2G",
    "timeout": 1800
})
# Returns: {"job_id": "kernel_test_...", "status": "starting"}

# Step 2: Check status (repeat every 10-30 seconds)
status = get_job_status({"job_id": result["job_id"]})
# Returns: {"status": "running", "elapsed_seconds": 45, ...}

# Step 3: When completed, get results
status = get_job_status({"job_id": result["job_id"]})
# Returns: {"status": "completed", "returncode": 0, "stdout": "...", ...}

AGENT GUIDANCE:
───────────────
When you start an async job:
1. Inform user: "Starting [operation] (job ID: xxx)..."
2. Wait 10-30 seconds
3. Check status with get_job_status()
4. If status is "running":
   - Inform user of progress: "Running (Xs elapsed)..."
   - Wait 10-30 seconds
   - Go back to step 3
5. If status is "completed" or "failed":
   - Report results to user
   - Show output/errors as appropriate
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
                        "description": "Maximum runtime in seconds (default: 3600)",
                        "default": 3600,
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
            name="get_job_status",
            description="""
Get the status of an async kernel test job.
This tool checks the current state of a job started with run_kernel_async().

⏱️  FAST OPERATION - Returns immediately (<1 second), no timeout risk!

Returns job information including:
- job_id: The job identifier
- status: Current state (starting, running, completed, failed, cancelled)
- elapsed_seconds: Time since job started
- start_time: When the job started (ISO format)

If job is completed or failed, also includes:
- returncode: Exit code of the command
- stdout: Command output (truncated if too large)
- stderr: Error output (if any)
- end_time: When the job finished
- total_time_seconds: Total execution time

Status values:
──────────────
- "starting": Job is initializing
- "running": Job is currently executing
- "completed": Job finished successfully (returncode 0)
- "failed": Job finished with error (returncode != 0)
- "cancelled": Job was cancelled

Polling strategy:
─────────────────
When status is "starting" or "running":
  → Wait 10-30 seconds before checking again
  → Inform user of progress
  → Continue polling until "completed", "failed", or "cancelled"

When status is "completed" or "failed":
  → Job is finished
  → Retrieve and display results to user
  → stdout/stderr contain the output

Parameters:
───────────
- job_id (required): The job ID returned by run_kernel_async()

Example usage:
──────────────
# Check job status
status = get_job_status({"job_id": "kernel_test_1234567890_abc123"})

# Response when running:
{
    "job_id": "kernel_test_...",
    "status": "running",
    "elapsed_seconds": 45,
    "start_time": "2025-12-15T12:34:56",
    "poll_again_in_seconds": 30
}

# Response when completed:
{
    "job_id": "kernel_test_...",
    "status": "completed",
    "returncode": 0,
    "elapsed_seconds": 300,
    "total_time_seconds": 300,
    "start_time": "2025-12-15T12:34:56",
    "end_time": "2025-12-15T12:39:56",
    "stdout": "...test output...",
    "stderr": ""
}

AGENT GUIDANCE:
───────────────
1. Call this repeatedly (every 10-30 seconds) while status is "running"
2. Update user with progress: "Test running (Xs elapsed)..."
3. When completed, show results to user
4. If failed, show error information from stdout/stderr
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned by run_kernel_async()",
                    },
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="cancel_job",
            description="""
Cancel a running async kernel test job.

This attempts to cancel a job that was started with run_kernel_async().

Note: Currently this marks the job as "cancelled" but does not forcibly
terminate the underlying process. The job will continue running but will
be marked as cancelled in the job system.

Parameters:
───────────
- job_id (required): The job ID to cancel

Returns:
────────
- success: Whether the cancellation was successful
- message: Description of what happened

Example:
────────
cancel_job({"job_id": "kernel_test_1234567890_abc123"})
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID to cancel",
                    },
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="list_jobs",
            description="""
List all active async kernel test jobs.

Shows all jobs in the system with their current status. Useful for:
- Debugging: See what jobs are running
- Recovery: Find job IDs if you lost track
- Monitoring: Check multiple running jobs

Automatically cleans up old jobs (>24 hours) before listing.

Returns:
────────
- jobs: Array of job objects with status information
- count: Number of jobs

Example:
────────
list_jobs({})
            """,
            inputSchema={
                "type": "object",
                "properties": {},
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
    if name == "run_kselftest":
        return await run_kselftest_handler(arguments)
    if name == "run_kernel_async":
        return await run_kernel_async_handler(arguments)
    if name == "get_job_status":
        return await get_job_status_handler(arguments)
    if name == "cancel_job":
        return await cancel_job_handler(arguments)
    if name == "list_jobs":
        return await list_jobs_handler()
    if name == "get_kernel_info":
        return await get_kernel_info(arguments)
    if name == "apply_patch":
        return await apply_patch(arguments)
    if name == "verify_kernel":
        return await verify_kernel(arguments)
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


async def verify_kernel(args: dict) -> list[TextContent]:
    """
    Verify a kernel commit by building and booting it.

    This validates that a specific commit both compiles and runs correctly.
    """
    kernel_dir = args.get("kernel_dir", ".")
    commit = args.get("commit")
    build_host = args.get("build_host")
    config_items = args.get("config_items", [])
    test_command = args.get("test_command", "uname -r")
    build_timeout = args.get("build_timeout", 600)  # 10 minutes for builds
    boot_timeout = args.get("boot_timeout", 300)

    kernel_path = Path(kernel_dir)

    # Check if kernel directory exists
    if not kernel_path.exists():
        result = {
            "success": False,
            "error": "kernel_dir_not_found",
            "message": f"Kernel directory {kernel_dir} does not exist",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Check if it's a git repository
    git_dir = kernel_path / ".git"
    if not git_dir.exists():
        result = {
            "success": False,
            "error": "not_a_git_repo",
            "message": f"Directory {kernel_dir} is not a git repository",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # If commit is specified, checkout that commit
    if commit:
        returncode, _, checkout_stderr = run_command(
            ["git", "checkout", commit], cwd=kernel_dir, timeout=30
        )
        if returncode != 0:
            result = {
                "success": False,
                "error": "git_checkout_failed",
                "message": f"Failed to checkout commit {commit}",
                "stderr": checkout_stderr,
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Get current commit info
    returncode, commit_sha, _ = run_command(
        ["git", "rev-parse", "HEAD"], cwd=kernel_dir, timeout=10
    )
    if returncode != 0:
        commit_sha = "unknown"
    else:
        commit_sha = commit_sha.strip()

    returncode, subject, _ = run_command(
        ["git", "log", "-1", "--format=%s"], cwd=kernel_dir, timeout=10
    )
    commit_subject = subject.strip() if returncode == 0 else "Unknown"

    result = {
        "commit_sha": commit_sha,
        "commit_short": commit_sha[:12] if commit_sha != "unknown" else "unknown",
        "commit_subject": commit_subject,
        "test_command": test_command,
    }

    # Build the kernel
    build_cmd = ["vng", "-v", "--build"]
    if build_host:
        build_cmd.extend(["--build-host", build_host])
    for config_item in config_items:
        build_cmd.extend(["--configitem", config_item])

    build_start = time.time()
    build_returncode, build_stdout, build_stderr = run_command(
        build_cmd, cwd=kernel_dir, timeout=build_timeout
    )
    build_time = time.time() - build_start

    result["build_command"] = shlex.join(build_cmd)
    result["build_time_seconds"] = round(build_time, 2)

    if build_returncode != 0:
        result["build_status"] = "FAILED"
        result["boot_status"] = "SKIPPED"
        result["overall_status"] = "FAILED"
        result["success"] = False
        # Include last 2000 chars of output for debugging
        result["build_stdout"] = (
            build_stdout[-2000:] if len(build_stdout) > 2000 else build_stdout
        )
        result["build_stderr"] = (
            build_stderr[-2000:] if len(build_stderr) > 2000 else build_stderr
        )
        result["message"] = "Kernel build failed"
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    result["build_status"] = "SUCCESS"

    # Boot the kernel (MANDATORY)
    # Use script wrapper for PTS requirement
    vng_boot_cmd = ["vng", "-v", "--", test_command]
    vng_boot_cmd_str = shlex.join(vng_boot_cmd)
    shell_cmd = f"script -q -c {shlex.quote(vng_boot_cmd_str)} /dev/null 2>&1"

    boot_start = time.time()
    boot_returncode, boot_stdout, boot_stderr = run_command(
        ["sh", "-c", shell_cmd], cwd=kernel_dir, timeout=boot_timeout
    )
    boot_time = time.time() - boot_start

    result["boot_command"] = vng_boot_cmd_str
    result["boot_time_seconds"] = round(boot_time, 2)

    if boot_returncode != 0:
        result["boot_status"] = "FAILED"
        result["overall_status"] = "FAILED"
        result["success"] = False
        # Include last 2000 chars of output for debugging
        result["boot_stdout"] = (
            boot_stdout[-2000:] if len(boot_stdout) > 2000 else boot_stdout
        )
        result["boot_stderr"] = (
            boot_stderr[-2000:] if len(boot_stderr) > 2000 else boot_stderr
        )
        result["message"] = "Kernel built successfully but boot test failed"
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Both build and boot succeeded!
    result["boot_status"] = "SUCCESS"
    result["overall_status"] = "PASSED"
    result["success"] = True
    # Include last 1000 chars of boot output
    result["boot_stdout"] = (
        boot_stdout[-1000:] if len(boot_stdout) > 1000 else boot_stdout
    )
    result["message"] = "Kernel verification passed: build and boot successful"

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def run_kselftest_handler(args: dict) -> list[TextContent]:
    """
    Run kernel selftests asynchronously with automatic build support.
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
    kernel_path = Path(kernel_dir)
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

    # Get settings
    kernel_image = args.get("kernel_image")
    build_timeout = 600  # Hard-coded 10 minutes for kselftest builds

    build_steps = []

    # Step 1: Rebuild kernel with test config (if config file exists)
    # Only rebuild for newly built kernels (not host or upstream kernels)
    if not kernel_image:
        test_config_path = test_path / "config"
        if test_config_path.exists():
            # Rebuild kernel with test config to ensure all required
            # configs are enabled
            rebuild_cmd = [
                "vng",
                "-v",
                "--build",
                "--force",
            ]

            # Pass both .config (to preserve old configs) and test config
            # (to add test requirements)
            kernel_config_path = kernel_path / ".config"
            if kernel_config_path.exists():
                rebuild_cmd.extend(["--config", str(kernel_config_path)])

            if test_config_path.exists():
                rebuild_cmd.extend(
                    ["--config", str(test_config_path.relative_to(kernel_path))]
                )

            rebuild_start = time.time()
            rebuild_returncode, rebuild_stdout, rebuild_stderr = run_command(
                rebuild_cmd,
                cwd=kernel_dir,
                timeout=3600,  # 1 hour timeout for kernel rebuild
            )
            rebuild_time = time.time() - rebuild_start

            if rebuild_returncode != 0:
                result = {
                    "success": False,
                    "error": "kernel_rebuild_failed",
                    "message": (
                        f"Failed to rebuild kernel with required configs for "
                        f"kselftest '{test_name}' (took {round(rebuild_time, 2)}s)"
                    ),
                    "config_file": str(test_config_path.relative_to(kernel_path)),
                    "rebuild_stdout": (
                        rebuild_stdout[-2000:]
                        if len(rebuild_stdout) > 2000
                        else rebuild_stdout
                    ),
                    "rebuild_stderr": (
                        rebuild_stderr[-2000:]
                        if len(rebuild_stderr) > 2000
                        else rebuild_stderr
                    ),
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            build_steps.append(
                f"kernel rebuilt with test configs (took {round(rebuild_time, 2)}s)"
            )

    # Step 2: Install kernel headers (required by most kselftests)
    headers_cmd = ["make", "headers_install"]
    headers_returncode, headers_stdout, headers_stderr = run_command(
        headers_cmd, cwd=kernel_dir, timeout=build_timeout
    )

    if headers_returncode != 0:
        result = {
            "success": False,
            "error": "headers_install_failed",
            "message": "Failed to install kernel headers (required for kselftests)",
            "headers_stdout": (
                headers_stdout[-2000:] if len(headers_stdout) > 2000 else headers_stdout
            ),
            "headers_stderr": (
                headers_stderr[-2000:] if len(headers_stderr) > 2000 else headers_stderr
            ),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Step 3: Build kselftest
    nproc_result = run_command(["nproc"], timeout=5)
    nproc = nproc_result[1].strip() if nproc_result[0] == 0 else "1"

    build_cmd = [
        "make",
        f"-j{nproc}",
        "-C",
        f"tools/testing/selftests/{test_name}",
    ]

    build_start = time.time()
    build_returncode, build_stdout, build_stderr = run_command(
        build_cmd, cwd=kernel_dir, timeout=build_timeout
    )
    build_time = time.time() - build_start

    if build_returncode != 0:
        result = {
            "success": False,
            "error": "kselftest_build_failed",
            "message": f"Failed to build kselftest '{test_name}' (took {round(build_time, 2)}s)",
            "build_stdout": (
                build_stdout[-2000:] if len(build_stdout) > 2000 else build_stdout
            ),
            "build_stderr": (
                build_stderr[-2000:] if len(build_stderr) > 2000 else build_stderr
            ),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    build_steps.append(f"kselftest '{test_name}' (built in {round(build_time, 2)}s)")

    # Build the kselftest command
    runner_args = args.get("runner_args", "")
    if runner_args:
        kselftest_cmd = f'make kselftest TARGETS="{test_name}" SKIP_TARGETS="" KSELFTEST_RUNNER_ARGS="{runner_args}"'
    else:
        kselftest_cmd = f'make kselftest TARGETS="{test_name}" SKIP_TARGETS=""'

    # Prepare arguments for run_kernel_async
    async_args = {
        "kernel_dir": kernel_dir,
        "command": kselftest_cmd,
        "memory": args.get("memory", "2G"),
        "timeout": args.get("timeout", 3600),
    }

    # Add kernel_image if provided
    if args.get("kernel_image"):
        async_args["kernel_image"] = args["kernel_image"]

    # Add optional parameters if provided
    if args.get("arch"):
        async_args["arch"] = args["arch"]
    if args.get("cpus"):
        async_args["cpus"] = args["cpus"]
    if args.get("network"):
        async_args["network"] = args["network"]

    # Generate unique job ID
    timestamp = int(time.time())
    job_id = f"kselftest_{test_name}_{timestamp}_{uuid.uuid4().hex[:8]}"

    # Build command string for display
    kernel_image = args.get("kernel_image")
    if kernel_image == "host":
        command_str = f"vng -vr -- {kselftest_cmd}"
        kernel_note = "Running on host kernel"
    elif kernel_image:
        command_str = f"vng -vr {kernel_image} -- {kselftest_cmd}"
        if kernel_image.startswith("v") and any(c.isdigit() for c in kernel_image):
            kernel_note = f"Running on upstream kernel {kernel_image}"
        else:
            kernel_note = f"Running on kernel image: {kernel_image}"
    else:
        command_str = f"vng -v -- {kselftest_cmd}"
        kernel_note = "Running on newly built kernel"

    # Create job object
    job = Job(job_id=job_id, command=command_str, args=async_args)

    # Store job
    with _jobs_lock:
        _active_jobs[job_id] = job

    # Start background thread
    thread = threading.Thread(
        target=_run_job_in_background, args=(job_id,), daemon=True
    )
    thread.start()

    # Wait for up to 60 seconds to see if job completes quickly
    job = _wait_for_job_completion(job_id, max_wait_seconds=60)

    if job and job.status in ("completed", "failed", "cancelled"):
        # Job completed within 60 seconds - return full results
        result = job.to_dict()
        result["success"] = True
        result["auto_completed"] = True
        result["test_name"] = test_name
        result["message"] = (
            f"Kselftest '{test_name}' completed automatically (finished in {round(job.elapsed_seconds(), 2)}s)"
        )

        # Add build information
        if build_steps:
            result["builds_performed"] = build_steps
        else:
            result["builds_performed"] = ["none (everything already built)"]

        if job.status == "completed":
            result["success_flag"] = job.returncode == 0
            if job.returncode != 0:
                result["warning"] = (
                    f"Test completed but command returned exit code {job.returncode}"
                )
        elif job.status == "failed":
            result["success_flag"] = False
        elif job.status == "cancelled":
            result["success_flag"] = False

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Job still running after 60 seconds - return job info for manual polling
    result = {
        "success": True,
        "job_id": job_id,
        "status": job.status if job else "starting",
        "test_name": test_name,
        "message": f"Kselftest '{test_name}' is still running after 60s. Use get_job_status() to check progress.",
        "command": command_str,
        "kernel_note": kernel_note,
        "poll_suggestion": "Wait 10 seconds before first status check",
        "expected_runtime": "Kselftests typically take 5-60+ minutes",
        "elapsed_seconds": round(job.elapsed_seconds(), 2) if job else 0,
    }

    # Add build information if any builds were performed
    if build_steps:
        result["builds_performed"] = build_steps
    else:
        result["builds_performed"] = ["none (everything already built)"]

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def run_kernel_async_handler(args: dict) -> list[TextContent]:
    """
    Start a kernel test asynchronously.
    Returns immediately with a job ID that can be used to check status.
    """
    # Generate unique job ID
    timestamp = int(time.time())
    job_id = f"kernel_test_{timestamp}_{uuid.uuid4().hex[:8]}"

    # Build command string for display
    command_parts = ["vng"]
    kernel_image = args.get("kernel_image")
    if kernel_image == "host":
        command_parts.append("-vr")
    elif kernel_image:
        command_parts.extend(["-vr", kernel_image])

    if args.get("command"):
        command_parts.extend(["--", args["command"]])
    elif args.get("interactive"):
        command_parts.append("(interactive)")
    else:
        command_parts.extend(["--", "uname -r"])

    command_str = " ".join(command_parts)

    # Create job object
    job = Job(job_id=job_id, command=command_str, args=args)

    # Store job
    with _jobs_lock:
        _active_jobs[job_id] = job

    # Start background thread
    thread = threading.Thread(
        target=_run_job_in_background, args=(job_id,), daemon=True
    )
    thread.start()

    # Wait for up to 60 seconds to see if job completes quickly
    job = _wait_for_job_completion(job_id, max_wait_seconds=60)

    if job and job.status in ("completed", "failed", "cancelled"):
        # Job completed within 60 seconds - return full results
        result = job.to_dict()
        result["success"] = True
        result["auto_completed"] = True
        result["message"] = (
            f"Job completed automatically (finished in {round(job.elapsed_seconds(), 2)}s)"
        )

        if job.status == "completed":
            result["success_flag"] = job.returncode == 0
            if job.returncode != 0:
                result["warning"] = (
                    f"Job completed but command returned exit code {job.returncode}"
                )
        elif job.status == "failed":
            result["success_flag"] = False
        elif job.status == "cancelled":
            result["success_flag"] = False

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Job still running after 60 seconds - return job info for manual polling
    result = {
        "success": True,
        "job_id": job_id,
        "status": job.status if job else "starting",
        "message": "Job is still running after 60s. Use get_job_status() to check progress.",
        "command": command_str,
        "poll_suggestion": "Wait 10 seconds before first status check",
        "elapsed_seconds": round(job.elapsed_seconds(), 2) if job else 0,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def get_job_status_handler(args: dict) -> list[TextContent]:
    """
    Get the current status of an async job.
    Returns immediately (fast, no timeout risk).
    """
    job_id = args.get("job_id")

    if not job_id:
        result = {
            "success": False,
            "error": "job_id is required",
            "message": "Please provide a job_id from run_kernel_async()",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Clean up old jobs first
    _cleanup_old_jobs()

    with _jobs_lock:
        if job_id not in _active_jobs:
            result = {
                "success": False,
                "error": "job_not_found",
                "message": f"Job {job_id} not found. It may have been cleaned up (>24h old) or never existed.",
                "help": "Use list_jobs() to see all active jobs.",
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        job = _active_jobs[job_id]

    # Convert job to dict
    result = job.to_dict()
    result["success"] = True

    # Add helpful messages and guidance based on status
    if job.status == "starting":
        result["message"] = "Job is starting up..."
        result["poll_again_in_seconds"] = 60
    elif job.status == "running":
        elapsed = result["elapsed_seconds"]
        result["message"] = f"Job is running ({elapsed}s elapsed)"
        result["poll_again_in_seconds"] = 10
        result["agent_guidance"] = (
            f"Wait {result['poll_again_in_seconds']} seconds before checking again"
        )
    elif job.status == "completed":
        result["message"] = "Job completed successfully"
        result["success_flag"] = job.returncode == 0
        if job.returncode != 0:
            result["warning"] = (
                f"Job completed but command returned exit code {job.returncode}"
            )
    elif job.status == "failed":
        result["message"] = "Job failed"
        result["success_flag"] = False
    elif job.status == "cancelled":
        result["message"] = "Job was cancelled"
        result["success_flag"] = False

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def cancel_job_handler(args: dict) -> list[TextContent]:
    """
    Cancel a running async job.
    Note: Currently just marks as cancelled, doesn't forcibly kill the process.
    """
    job_id = args.get("job_id")

    if not job_id:
        result = {
            "success": False,
            "error": "job_id is required",
            "message": "Please provide a job_id to cancel",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    with _jobs_lock:
        if job_id not in _active_jobs:
            result = {
                "success": False,
                "error": "job_not_found",
                "message": f"Job {job_id} not found",
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        job = _active_jobs[job_id]

        if job.status in ("completed", "failed", "cancelled"):
            result = {
                "success": False,
                "error": "job_already_finished",
                "message": f"Job {job_id} has already finished with status: {job.status}",
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Mark as cancelled
        job.status = "cancelled"
        job.end_time = time.time()

        # Note: To actually kill the process, we'd need to store the Popen object
        # and call process.terminate(). For now, we just mark it as cancelled.
        result = {
            "success": True,
            "job_id": job_id,
            "message": "Job marked as cancelled",
            "note": "The underlying process may still be running. This marks the job as cancelled in the job system.",
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def list_jobs_handler() -> list[TextContent]:
    """
    List all active async jobs.
    Automatically cleans up old jobs (>24 hours) first.
    """
    # Clean up old jobs
    _cleanup_old_jobs()

    with _jobs_lock:
        jobs = [job.to_dict() for job in _active_jobs.values()]

    # Sort by start time (newest first)
    jobs.sort(key=lambda j: j.get("start_time", ""), reverse=True)

    result = {
        "success": True,
        "jobs": jobs,
        "count": len(jobs),
        "message": f"Found {len(jobs)} active job(s)",
    }

    if len(jobs) == 0:
        result["note"] = (
            "No active jobs. Jobs older than 24 hours are automatically cleaned up."
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
