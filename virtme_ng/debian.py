# -*- mode: python -*-
# Copyright 2024 virtme-ng contributors
"""virtme-ng: Debian cloud image integration."""

import glob
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
from subprocess import (
    DEVNULL,
    PIPE,
    CalledProcessError,
    Popen,
    check_call,
    check_output,
)


def _get_run_helpers():
    """Lazy import to avoid circular dependency."""
    from virtme_ng.run import arg_fail, check_call_cmd

    return arg_fail, check_call_cmd


def arg_fail(message, show_usage=True):
    """Proxy to run.arg_fail (avoids circular import at module load)."""
    _af, _ = _get_run_helpers()
    _af(message, show_usage=show_usage)


def check_call_cmd(command, quiet=False, dry_run=False, pass_stdin=False):
    """Proxy to run.check_call_cmd."""
    _, _ccc = _get_run_helpers()
    _ccc(command, quiet=quiet, dry_run=dry_run, pass_stdin=pass_stdin)


DEBIAN_IMAGE_NAME = "debian-sid-generic-amd64-daily"
DEBIAN_IMAGE_URL = (
    f"https://cloud.debian.org/images/cloud/sid/daily/latest/{DEBIAN_IMAGE_NAME}.qcow2"
)
SSH_PORT = 2222


def get_ssh_key_path():
    """Return SSH key path inside .virtme_debian/."""
    return os.path.join(get_debian_dir(), "id_ed25519")


def check_port_available(port):
    """Check if TCP port is available. Kill stale QEMU using same image if needed."""
    import socket as sock

    s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        s.close()
        return False


def get_debian_dir():
    """Return <kernel_dir>/.virtme_debian as the artifact directory."""
    return os.path.join(os.getcwd(), ".virtme_debian")


class DebianMixin:
    """Mixin providing --debian functionality for KernelSource."""

    def _debian_build(self, args):
        """Setup cloud image, copy config, build bindeb-pkg, install .deb into VM."""
        os.makedirs(get_debian_dir(), exist_ok=True)
        kernel_dir = os.getcwd()

        qcow2 = os.path.join(get_debian_dir(), f"{DEBIAN_IMAGE_NAME}.qcow2")
        cloud_img = os.path.join(get_debian_dir(), f"{DEBIAN_IMAGE_NAME}.img")

        # Check if a previous cloud image exists
        image_exists = os.path.isfile(qcow2) and os.path.isfile(cloud_img)

        if image_exists:
            print("Existing Debian cloud image found.")
            print("  1) Reset (re-download, re-initialize, and install kernel)")
            print("  2) Install newer build kernel only")
            choice = input("Choose [1/2]: ").strip()
            if choice == "1":
                os.remove(qcow2)
                os.remove(cloud_img)
            elif hasattr(args, "resize") and args.resize:
                print(f"Resizing image to {args.resize}...")
                check_call(["qemu-img", "resize", qcow2, args.resize])

        # Step 1: Setup cloud image if needed
        self._debian_setup_image(args)

        qemu = self._debian_find_qemu(args)

        # Step 2: Copy /boot/config-* from cloud image to host .config
        if not os.path.isfile(os.path.join(kernel_dir, ".config")):
            print("=== Copying config from cloud image ===")
            self._debian_boot_vm_and_ssh(
                qemu,
                qcow2,
                cloud_img,
                get_debian_dir(),
                get_ssh_key_path(),
                "cat /boot/config-$(uname -r)",
                output_file=os.path.join(kernel_dir, ".config"),
                verbose=args.verbose,
            )

        # Step 3: Apply --config fragments and --configitem
        if hasattr(args, "config") and args.config:
            merge_cmd = ["./scripts/kconfig/merge_config.sh", "-m", ".config"]
            merge_cmd += args.config
            check_call(merge_cmd)

        if hasattr(args, "configitem") and args.configitem:
            for item in args.configitem:
                key, _, val = item.partition("=")
                if val:
                    check_call(["./scripts/config", "--set-val", key, val])
                else:
                    check_call(["./scripts/config", "--enable", key])
        check_call(["make", "olddefconfig"])

        # Step 4: make bindeb-pkg (keep .deb in kernel dir)
        jobs = str(args.jobs) if args.jobs else self.cpus
        cmd = ["nice", "make", f"-j{jobs}", "bindeb-pkg"]
        cmd += args.envs
        if args.verbose:
            print(f"cmd: {shlex.join(cmd)}")
        check_call_cmd(cmd, quiet=not args.verbose, dry_run=args.dry_run)
        if args.dry_run:
            return

        # Find the linux-image .deb (bindeb-pkg outputs to parent dir)
        parent = os.path.dirname(kernel_dir)
        debs = [
            f
            for f in glob.glob(os.path.join(parent, "linux-image-*.deb"))
            if "dbg" not in f
        ]
        if not debs:
            arg_fail("error: no linux-image .deb found after bindeb-pkg")
        deb_file = sorted(debs, key=os.path.getmtime)[-1]

        # Move .deb into .virtme_debian/
        debian_dir = get_debian_dir()
        deb_dest = os.path.join(debian_dir, os.path.basename(deb_file))
        shutil.move(deb_file, deb_dest)
        deb_file = deb_dest
        print(f"Using deb: {deb_file}")

        # Extract vmlinuz from .deb
        kver = self._debian_extract_boot_files(deb_file)

        # Step 5: Boot VM, mount kernel dir via 9p, install .deb
        deb_basename = os.path.basename(deb_file)

        print("=== Installing kernel .deb into VM ===")
        install_script = (
            "set -e && "
            "mkdir -p /home/debian/vng && "
            "mount -t 9p -o trans=virtio vngshare /home/debian/vng && "
            f"dpkg -i /home/debian/vng/.virtme_debian/{deb_basename} && "
            f"update-initramfs -c -k {kver} 2>/dev/null || true && "
            f"grub-set-default 0 && update-grub && "
            "echo INSTALL_OK"
        )
        self._debian_boot_vm_and_ssh(
            qemu,
            qcow2,
            cloud_img,
            kernel_dir,
            get_ssh_key_path(),
            install_script,
            verbose=args.verbose,
        )

        print("=== Debian build complete ===")
        print(f"  .deb: {deb_file}")
        print(f"  kernel: {kver}")
        print("  Run with: vng --debian")

    def _debian_run(self, args):
        """Boot the Debian cloud image with the installed custom kernel."""
        if hasattr(args, "target") and args.target:
            qcow2 = args.target
        else:
            qcow2 = os.path.join(get_debian_dir(), f"{DEBIAN_IMAGE_NAME}.qcow2")
        cloud_img = qcow2.replace(".qcow2", ".img")

        if not os.path.isfile(qcow2):
            arg_fail(
                "error: Debian cloud image not found. Run 'vng --build --debian' first.",
                show_usage=False,
            )

        qemu = self._debian_find_qemu(args)
        kernel_dir = os.getcwd()

        if not check_port_available(SSH_PORT):
            arg_fail(
                f"error: port {SSH_PORT} is already in use. "
                "Is another VM running? Kill it first.",
                show_usage=False,
            )

        cmd = [
            qemu,
            "-m",
            "8192",
            "-smp",
            "4",
            "-enable-kvm",
            "-drive",
            f"file={qcow2},format=qcow2",
            "-drive",
            f"file={cloud_img},format=raw,media=cdrom",
            "-net",
            "nic",
            "-net",
            f"user,hostfwd=tcp::{SSH_PORT}-:22",
            "-virtfs",
            f"local,path={kernel_dir},mount_tag=vngshare,security_model=none",
        ]

        if args.sound:
            cmd += ["-device", "intel-hda", "-device", "hda-duplex"]

        if args.graphics:
            cmd += [
                "-display",
                "gtk,grab-on-hover=on" if os.environ.get("DISPLAY") else "vnc=:0",
                "-vga",
                "virtio",
                "-usb",
                "-device",
                "usb-ehci,id=ehci",
                "-device",
                "qemu-xhci,id=xhci",
                "-device",
                "virtio-scsi-pci,id=scsi0",
                "-monitor",
                "unix:/tmp/qemu-monitor.sock,server,nowait",
            ]
        elif hasattr(args, "ssh") and args.ssh is not None:
            # SSH mode: boot headless in background, user connects via SSH
            cmd += [
                "-display",
                "none",
                "-vga",
                "none",
                "-serial",
                "null",
                "-monitor",
                "none",
                "-daemonize",
            ]
        else:
            cmd += ["-display", "none", "-vga", "none", "-serial", "mon:stdio"]

        if args.verbose:
            print(f"cmd: {shlex.join(cmd)}")

        if args.exec:
            self._debian_run_exec(cmd, args, get_ssh_key_path())
        elif args.graphics:
            self._debian_run_gui(cmd, args)
        elif hasattr(args, "ssh") and args.ssh is not None:
            self._debian_run_ssh(cmd, args)
        else:
            if args.dry_run:
                print(shlex.join(cmd))
                return
            os.execvp(cmd[0], cmd)

    def _debian_find_qemu(self, args):
        """Find qemu-system-x86_64 binary."""
        qemu = args.qemu if hasattr(args, "qemu") and args.qemu else None
        if qemu is None:
            qemu = shutil.which("qemu-system-x86_64")
        if qemu is None:
            candidate = os.path.join(
                str(Path.home()), "qemu", "build", "qemu-system-x86_64"
            )
            if os.path.isfile(candidate):
                qemu = candidate
        if qemu is None:
            arg_fail("error: qemu-system-x86_64 not found")
        return qemu

    def _debian_setup_image(self, args):
        """Download and configure Debian cloud image if not present."""
        qcow2 = os.path.join(get_debian_dir(), f"{DEBIAN_IMAGE_NAME}.qcow2")
        cloud_img = os.path.join(get_debian_dir(), f"{DEBIAN_IMAGE_NAME}.img")

        if not os.path.isfile(get_ssh_key_path()):
            print("Generating SSH automation key...")
            check_call(
                [
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-f",
                    get_ssh_key_path(),
                    "-q",
                ]
            )

        if os.path.isfile(qcow2) and os.path.isfile(cloud_img):
            return

        if not os.path.isfile(qcow2):
            print("Downloading Debian cloud image...")
            check_call(["wget", "-O", qcow2, DEBIAN_IMAGE_URL])

        if hasattr(args, "resize") and args.resize:
            print(f"Resizing image to {args.resize}...")
            check_call(["qemu-img", "resize", qcow2, args.resize])

        ssh_pubkey = Path(get_ssh_key_path() + ".pub").read_text().strip()
        passwd_hash = (
            check_output(["mkpasswd", "-m", "sha-512", "debian"]).decode().strip()
        )

        user_data = os.path.join(get_debian_dir(), "user-data")
        with open(user_data, "w") as f:
            f.write(f"""#cloud-config
users:
  - name: debian
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    passwd: "{passwd_hash}"
    ssh_authorized_keys:
      - {ssh_pubkey}
  - name: root
    lock_passwd: false
    passwd: "{passwd_hash}"
    ssh_authorized_keys:
      - {ssh_pubkey}

ssh_pwauth: true
disable_root: false
chpasswd: {{ expire: False }}

runcmd:
  - sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
  - systemctl restart ssh
""")
        meta_data = os.path.join(get_debian_dir(), "meta-data")
        Path(meta_data).touch()
        check_call(["cloud-localds", cloud_img, user_data, meta_data])
        print("Cloud image setup complete.")

    def _debian_extract_boot_files(self, deb_file):
        """Extract vmlinuz from a linux-image .deb."""
        extract_dir = os.path.join(get_debian_dir(), "extracted")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        check_call(["ar", "x", deb_file, "data.tar.xz"], cwd=extract_dir)
        check_call(["tar", "-xf", "data.tar.xz"], cwd=extract_dir)
        os.remove(os.path.join(extract_dir, "data.tar.xz"))

        vmlinuz_files = glob.glob(os.path.join(extract_dir, "boot", "vmlinuz-*"))
        if not vmlinuz_files:
            arg_fail("error: vmlinuz not found in .deb")

        kver = os.path.basename(vmlinuz_files[0]).replace("vmlinuz-", "")
        with open(os.path.join(get_debian_dir(), "kver"), "w") as f:
            f.write(kver)

        shutil.rmtree(extract_dir)
        return kver

    def _debian_boot_vm_and_ssh(
        self,
        qemu,
        qcow2,
        cloud_img,
        share_path,
        ssh_key,
        remote_cmd,
        output_file=None,
        verbose=False,
    ):
        """Boot VM, wait for SSH, run command, shutdown. With verbose=True shows serial."""
        if not check_port_available(SSH_PORT):
            arg_fail(
                f"error: port {SSH_PORT} is already in use. "
                "Is another VM running? Kill it first.",
                show_usage=False,
            )
        vm_cmd = [
            qemu,
            "-m",
            "8192",
            "-smp",
            "4",
            "-enable-kvm",
            "-drive",
            f"file={qcow2},format=qcow2",
            "-drive",
            f"file={cloud_img},format=raw,media=cdrom",
            "-net",
            "nic",
            "-net",
            f"user,hostfwd=tcp::{SSH_PORT}-:22",
            "-virtfs",
            f"local,path={share_path},mount_tag=vngshare,security_model=none",
            "-display",
            "none",
            "-vga",
            "none",
        ]
        if verbose:
            vm_cmd += ["-serial", "mon:stdio"]
            vm_proc = Popen(vm_cmd)
        else:
            vm_cmd += ["-serial", "null", "-monitor", "none", "-daemonize"]
            check_call(vm_cmd)
            vm_proc = None

        ssh_opts = [
            "-i",
            ssh_key,
            "-p",
            str(SSH_PORT),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
        ]

        print("Waiting for VM SSH...")
        for _ in range(180):
            try:
                check_call(
                    ["ssh"] + ssh_opts + ["root@localhost", "true"],
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                )
                break
            except (CalledProcessError, OSError):
                time.sleep(2)
        else:
            arg_fail("error: VM SSH timeout")

        ssh_cmd = ["ssh"] + ssh_opts + ["root@localhost"]

        if output_file:
            output = check_output(ssh_cmd + ["bash", "-c", remote_cmd])
            with open(output_file, "wb") as f:
                f.write(output)
        else:
            check_call(ssh_cmd + ["bash", "-c", remote_cmd])

        try:
            check_call(ssh_cmd + ["poweroff"], stdout=DEVNULL, stderr=DEVNULL)
        except (CalledProcessError, OSError):
            pass
        if vm_proc:
            vm_proc.wait()
        else:
            time.sleep(5)

    def _debian_run_ssh(self, qemu_cmd, args):
        """Boot VM in background, wait for SSH, then open SSH session."""
        if args.dry_run:
            print(shlex.join(qemu_cmd))
            return

        check_call(qemu_cmd)
        print("VM started in background. Waiting for SSH...")

        ssh_opts = [
            "-i",
            get_ssh_key_path(),
            "-p",
            str(SSH_PORT),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]

        for _ in range(90):
            try:
                check_call(
                    ["ssh"]
                    + ssh_opts
                    + ["-o", "ConnectTimeout=3", "root@localhost", "true"],
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                )
                break
            except (CalledProcessError, OSError):
                time.sleep(2)
        else:
            arg_fail("error: VM SSH timeout", show_usage=False)

        print("SSH ready. Connecting...")
        print(
            f"  (To reconnect: ssh -i {get_ssh_key_path()} -p {SSH_PORT} root@localhost)"
        )
        print(
            f"  (To stop VM:   ssh -i {get_ssh_key_path()} -p {SSH_PORT} root@localhost poweroff)"
        )
        os.execvp("ssh", ["ssh"] + ssh_opts + ["root@localhost"])

    def _debian_run_gui(self, qemu_cmd, args):
        """Launch VM with graphical display."""
        if args.dry_run:
            print(shlex.join(qemu_cmd))
            return
        os.execvp(qemu_cmd[0], qemu_cmd)

    def _debian_run_exec(self, qemu_cmd, args, ssh_key):
        """Boot VM, wait for SSH, execute command via SSH, shutdown."""
        vm_proc = Popen(qemu_cmd, stdin=PIPE)

        ssh_opts = [
            "-i",
            ssh_key,
            "-p",
            str(SSH_PORT),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
        ]

        print("Waiting for VM SSH...")
        for _ in range(90):
            try:
                check_call(
                    ["ssh"] + ssh_opts + ["root@localhost", "true"],
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                )
                break
            except (CalledProcessError, OSError):
                time.sleep(2)
        else:
            vm_proc.terminate()
            arg_fail("error: VM SSH timeout")

        ssh_cmd = ["ssh"] + ssh_opts + ["root@localhost"]

        try:
            check_call(
                ssh_cmd
                + [
                    "bash",
                    "-c",
                    "mkdir -p /home/debian/vng && "
                    "mount -t 9p -o trans=virtio vngshare /home/debian/vng 2>/dev/null || true",
                ],
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
        except CalledProcessError:
            pass

        exec_cmd = args.exec
        if exec_cmd.startswith("./"):
            exec_cmd = "/home/debian/vng/" + exec_cmd[2:]

        ret = 0
        try:
            check_call(ssh_cmd + ["bash", "-c", f"cd /home/debian/vng && {exec_cmd}"])
        except CalledProcessError as e:
            ret = e.returncode

        try:
            check_call(ssh_cmd + ["poweroff"], stdout=DEVNULL, stderr=DEVNULL)
        except (CalledProcessError, OSError):
            pass
        vm_proc.wait(timeout=30)
        sys.exit(ret)
