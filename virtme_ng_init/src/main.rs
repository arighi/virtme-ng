// SPDX-License-Identifier: GPL-3.0

//! virtme-ng-init
//!
//! This program serves as an extremely lightweight init process for `virtme-ng` in order to speed
//! up boot time.
//!
//! Its primary purpose is to perform any necessary initialization in the virtualized environment,
//! such as mounting filesystems, starting essential services, and configuring the system before
//! handing over control to the main user-space processes (typicall a shell session).
//!
//! Author: Andrea Righi <andrea.righi@canonical.com>

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::engine::Engine as _;

use nix::fcntl::{open, OFlag};
use nix::libc;
use nix::sys::reboot;
use nix::sys::stat::Mode;
use nix::sys::utsname::uname;
use nix::unistd::sethostname;
use std::env;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::os::fd::{AsRawFd, IntoRawFd};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{exit, id, Command, Stdio};
use std::thread;
use std::time::Duration;

#[macro_use]
mod utils;

#[cfg(test)]
mod test;

struct MountInfo {
    source: &'static str,
    target: &'static str,
    fs_type: &'static str,
    flags: usize,
    fsdata: &'static str,
}

const KERNEL_MOUNTS: &[MountInfo] = &[
    MountInfo {
        source: "proc",
        target: "/proc",
        fs_type: "proc",
        flags: (libc::MS_NOSUID | libc::MS_NOEXEC | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "sys",
        target: "/sys",
        fs_type: "sysfs",
        flags: (libc::MS_NOSUID | libc::MS_NOEXEC | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "run",
        target: "/run",
        fs_type: "tmpfs",
        flags: 0,
        fsdata: "mode=0755",
    },
    MountInfo {
        source: "devtmpfs",
        target: "/dev",
        fs_type: "devtmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NOEXEC) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "configfs",
        target: "/sys/kernel/config",
        fs_type: "configfs",
        flags: 0,
        fsdata: "",
    },
    MountInfo {
        source: "debugfs",
        target: "/sys/kernel/debug",
        fs_type: "debugfs",
        flags: 0,
        fsdata: "",
    },
    MountInfo {
        source: "tracefs",
        target: "/sys/kernel/tracing",
        fs_type: "tracefs",
        flags: 0,
        fsdata: "",
    },
    MountInfo {
        source: "securityfs",
        target: "/sys/kernel/security",
        fs_type: "securityfs",
        flags: 0,
        fsdata: "",
    },
];

const SYSTEM_MOUNTS: &[MountInfo] = &[
    MountInfo {
        source: "devpts",
        target: "/dev/pts",
        fs_type: "devpts",
        flags: (libc::MS_NOSUID | libc::MS_NOEXEC) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/dev/shm",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/log",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/tmp",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/spool/rsyslog",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/portables",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/machines",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/private",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/sudo",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/apt",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/cache",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/snapd/cookie",
        fs_type: "tmpfs",
        flags: (libc::MS_NOSUID | libc::MS_NODEV) as usize,
        fsdata: "",
    },
];

const USER_SCRIPT: &str = "/run/tmp/.virtme-script";

fn check_init_pid() {
    if id() != 1 {
        log!("must be run as PID 1");
        exit(1);
    }
}

fn poweroff() {
    unsafe {
        libc::sync();
    }
    match reboot::reboot(reboot::RebootMode::RB_POWER_OFF) {
        Ok(_) => exit(0),
        Err(err) => {
            log!("error powering off: {}", err);
            exit(1);
        }
    }
}

fn configure_environment() {
    env::set_var("PATH", "/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin");
}

fn get_kernel_version(show_machine: bool) -> String {
    let utsname = match uname() {
        Ok(utsname) => utsname,
        Err(_) => return "None".to_string(),
    };
    let release = utsname.release().to_string_lossy();
    if show_machine {
        let machine = utsname.machine().to_string_lossy();
        format!("{} {}", release, machine)
    } else {
        release.into_owned()
    }
}

fn get_legacy_active_console() -> Option<String> {
    // See Documentation/filesystems/proc.rst for /proc/consoles documentation.
    match File::open("/proc/consoles") {
        Ok(file) => {
            let reader = BufReader::new(file);

            // .flatten() ignores lines with reading errors
            for line in reader.lines().flatten() {
                if line.chars().nth(27) == Some('C') {
                    let console = line.split(' ').next()?;
                    return Some(format!("/dev/{}", console));
                }
            }
            None
        }
        Err(error) => {
            log!("failed to open /proc/consoles: {}", error);
            None
        }
    }
}

fn get_active_console() -> Option<String> {
    if let Ok(console) = env::var("virtme_console") {
        Some(format!("/dev/{}", console))
    } else {
        get_legacy_active_console()
    }
}

fn configure_limits() {
    if let Ok(nr_open) = env::var("nr_open") {
        if let Ok(mut file) = OpenOptions::new().write(true).open("/proc/sys/fs/nr_open") {
            file.write_all(nr_open.as_bytes())
                .expect("Failed to write nr_open");
        }
    }
}

fn configure_hostname() {
    if let Ok(hostname) = env::var("virtme_hostname") {
        if let Err(err) = sethostname(hostname) {
            log!("failed to change hostname: {}", err);
        }
    } else {
        log!("virtme_hostname is not defined");
    }
}

fn run_systemd_tmpfiles() {
    if !Path::new("/etc/systemd").exists() {
        return;
    }
    let args: &[&str] = &[
        "--create",
        "--boot",
        "--exclude-prefix=/dev",
        "--exclude-prefix=/root",
    ];
    utils::run_cmd("systemd-tmpfiles", args);
}

fn generate_fstab() -> io::Result<()> {
    utils::create_file("/run/tmp/fstab", 0o0664, "").ok();
    utils::do_mount(
        "/run/tmp/fstab",
        "/etc/fstab",
        "",
        libc::MS_BIND as usize,
        "",
    );
    Ok(())
}

fn generate_shadow() -> io::Result<()> {
    utils::create_file("/run/tmp/shadow", 0o0644, "").ok();

    let input_file = File::open("/etc/passwd")?;
    let output_file = File::create("/run/tmp/shadow")?;

    let reader = BufReader::new(input_file);
    let mut writer = BufWriter::new(output_file);

    for line in reader.lines() {
        if let Some((username, _)) = line?.split_once(':') {
            writeln!(writer, "{}:!:::::::", username)?;
        }
    }
    utils::do_mount(
        "/run/tmp/shadow",
        "/etc/shadow",
        "",
        libc::MS_BIND as usize,
        "",
    );

    Ok(())
}

fn generate_sudoers() -> io::Result<()> {
    let fname = "/run/tmp/sudoers";
    let mut content = "Defaults secure_path=\"/usr/sbin:/usr/bin:/sbin:/bin\"\n".to_string();
    content += "root ALL = (ALL) NOPASSWD: ALL\n";
    if let Ok(user) = env::var("virtme_user") {
        content += &format!("{} ALL = (ALL) NOPASSWD: ALL\n", user);
    }
    if !Path::new("/etc/sudoers").exists() {
        utils::create_file("/etc/sudoers", 0o0440, "").unwrap_or_else(|_| {});
    }
    utils::create_file(fname, 0o0440, &content).ok();
    utils::do_mount(fname, "/etc/sudoers", "", libc::MS_BIND as usize, "");
    Ok(())
}

// The /etc/lvm is usually only read/write by root. In order to allow commands like pvcreate to be
// run on rootless users just create a dummy directory and bind mount it in the same place.
fn generate_lvm() -> io::Result<()> {
    utils::do_mkdir("/run/tmp/lvm");
    utils::do_mount("/run/tmp/lvm", "/etc/lvm/", "", libc::MS_BIND as usize, "");
    Ok(())
}

fn generate_hosts() -> io::Result<()> {
    if let Ok(hostname) = env::var("virtme_hostname") {
        std::fs::copy("/etc/hosts", "/run/tmp/hosts")?;
        let mut h = OpenOptions::new()
            .write(true)
            .append(true)
            .open("/run/tmp/hosts")?;
        writeln!(h, "\n127.0.0.1 {}\n::1 {}", hostname, hostname)?;
        utils::do_mount(
            "/run/tmp/hosts",
            "/etc/hosts",
            "",
            libc::MS_BIND as usize,
            "",
        );
    }
    Ok(())
}

fn override_system_files() {
    generate_fstab().ok();
    generate_shadow().ok();
    generate_sudoers().ok();
    generate_hosts().ok();
    generate_lvm().ok();
}

fn set_cwd() {
    if let Ok(dir) = env::var("virtme_chdir") {
        if let Err(err) = env::set_current_dir(dir) {
            log!("error changing directory: {}", err);
        }
    }
}

fn symlink_fds() {
    let fd_links = [
        ("/proc/self/fd", "/dev/fd"),
        ("/proc/self/fd/0", "/dev/stdin"),
        ("/proc/self/fd/1", "/dev/stdout"),
        ("/proc/self/fd/2", "/dev/stderr"),
    ];

    // Install /proc/self/fd symlinks into /dev if not already present.
    for (src, dst) in fd_links.iter() {
        if !std::path::Path::new(dst).exists() {
            utils::do_symlink(src, dst);
        }
    }
}

fn mount_kernel_filesystems() {
    for mount_info in KERNEL_MOUNTS {
        // In the case where a rootfs is specified when launching virtme-ng, it
        // mounts /run and /run/virtme/guesttools prior to executing
        // virtme-ng-init. We do not want to re-mount /run, as we will lose
        // access to guesttools, which is required for network setup.
        //
        // Note, get_test_tools_dir() relies on /proc, so that must be mounted
        // prior to /run.
        if mount_info.target == "/run" {
            if let Some(guest_tools_dir) = get_guest_tools_dir() {
                if guest_tools_dir.starts_with("/run") {
                    log!("/run previously mounted, skipping");
                    continue;
                }
            }
        }
        utils::do_mount(
            mount_info.source,
            mount_info.target,
            mount_info.fs_type,
            mount_info.flags,
            mount_info.fsdata,
        )
    }
}

fn mount_cgroupfs() {
    // If SYSTEMD_CGROUP_ENABLE_LEGACY_FORCE=1 is passed we can mimic systemd's behavior and mount
    // the legacy cgroup v1 layout.
    let cmdline = std::fs::read_to_string("/proc/cmdline").unwrap();
    if cmdline.contains("SYSTEMD_CGROUP_ENABLE_LEGACY_FORCE=1") {
        utils::do_mount("cgroup", "/sys/fs/cgroup", "tmpfs", 0, "");
        let subsystems = vec!["cpu", "cpuacct", "blkio", "memory", "devices", "pids"];
        for subsys in &subsystems {
            let target = format!("/sys/fs/cgroup/{}", subsys);
            utils::do_mkdir(&target);
            // Don't treat failure as critical here, since the kernel may not
            // support all the legacy cgroups.
            utils::do_mount(subsys, &target, "cgroup", 0, subsys);
        }
    } else {
        utils::do_mount("cgroup2", "/sys/fs/cgroup", "cgroup2", 0, "");
    }
}

fn mount_virtme_overlays() {
    utils::do_mkdir("/run/tmp/");
    for (key, path) in env::vars() {
        if key.starts_with("virtme_rw_overlay") {
            let dir = &format!("/run/tmp/{}", key);
            let upperdir = &format!("{}/upper", dir);
            let workdir = &format!("{}/work", dir);
            let mnt_opts = &format!(
                "xino=off,lowerdir={},upperdir={},workdir={}",
                path, upperdir, workdir
            );
            utils::do_mkdir(dir);
            utils::do_mkdir(upperdir);
            utils::do_mkdir(workdir);
            let result = utils::do_mount_check(&key, &path, "overlay", 0, mnt_opts);
            if result.is_err() {
                // Old kernels don't support xino=on|off, re-try without this option.
                let mnt_opts = &format!(
                    "lowerdir={},upperdir={},workdir={}",
                    path, upperdir, workdir
                );
                utils::do_mount(&key, &path, "overlay", 0, mnt_opts);
            }
        }
    }
}

fn mount_virtme_initmounts() {
    for (key, path) in env::vars() {
        if key.starts_with("virtme_initmount") {
            utils::do_mkdir(&path);
            utils::do_mount(
                &key.replace('_', "."),
                &path,
                "9p",
                0,
                "version=9p2000.L,trans=virtio,access=any",
            );
        }
    }
}

fn mount_kernel_modules() {
    let kver = get_kernel_version(false);
    let mod_dir = format!("/lib/modules/{}", kver);

    // Make sure to always have /lib/modules, otherwise we won't be able to configure kmod support
    // properly (this can happen in some container environments, such as docker).
    if !Path::new(&mod_dir).exists() {
        utils::do_mkdir("/lib/modules");
    }

    if env::var("virtme_root_mods").is_ok() {
        // /lib/modules is already set up.
    } else if let Ok(dir) = env::var("virtme_link_mods") {
        utils::do_mount("none", "/lib/modules/", "tmpfs", 0, "");
        utils::do_symlink(&dir, &mod_dir);
    } else if Path::new(&mod_dir).exists() {
        // We have mismatched modules. Mask them off.
        utils::do_mount("disallow_kmod", &mod_dir, "tmpfs", 0, "ro,mode=0000");
    }
}

fn mount_sys_filesystems() {
    utils::do_mkdir("/dev/pts");
    utils::do_mkdir("/dev/shm");
    utils::do_mkdir("/run/dbus");

    for mount_info in SYSTEM_MOUNTS {
        utils::do_mount(
            mount_info.source,
            mount_info.target,
            mount_info.fs_type,
            mount_info.flags,
            mount_info.fsdata,
        )
    }
}

fn fix_dpkg_locks() {
    if !Path::new("/var/lib/dpkg").exists() {
        return;
    }
    let lock_files = [
        "/var/lib/dpkg/lock",
        "/var/lib/dpkg/lock-frontend",
        "/var/lib/dpkg/triggers/Lock",
    ];
    for path in lock_files {
        let fname = Path::new(path)
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("");
        if fname.is_empty() {
            continue;
        }
        let src_file = format!("/run/tmp/{}", fname);
        utils::create_file(&src_file, 0o0640, "").ok();
        utils::do_mount(&src_file, path, "", libc::MS_BIND as usize, "");
    }
}

fn fix_packaging_files() {
    fix_dpkg_locks();
}

fn disable_uevent_helper() {
    let uevent_helper_path = "/sys/kernel/uevent_helper";

    if Path::new(uevent_helper_path).exists() {
        // This kills boot performance.
        log!("you have CONFIG_UEVENT_HELPER on, turn it off");
        let mut file = OpenOptions::new().write(true).open(uevent_helper_path).ok();
        match &mut file {
            Some(file) => {
                write!(file, "").ok();
            }
            None => {
                log!("error opening {}", uevent_helper_path);
            }
        }
    }
}

fn find_udevd() -> Option<PathBuf> {
    let static_candidates = [
        PathBuf::from("/usr/lib/systemd/systemd-udevd"),
        PathBuf::from("/lib/systemd/systemd-udevd"),
    ];
    let path = env::var("PATH").unwrap_or_else(|_| String::new());
    let path_candidates = path.split(':').map(|dir| Path::new(dir).join("udevd"));

    static_candidates
        .into_iter()
        .chain(path_candidates)
        .find(|path| path.exists())
}

fn run_udevd() -> Option<thread::JoinHandle<()>> {
    if let Some(udevd_path) = find_udevd() {
        let handle = thread::spawn(move || {
            disable_uevent_helper();
            let args: &[&str] = &["--daemon", "--resolve-names=never"];
            utils::run_cmd(udevd_path, args);
            log!("triggering udev coldplug");
            utils::run_cmd("udevadm", &["trigger", "--type=subsystems", "--action=add"]);
            utils::run_cmd("udevadm", &["trigger", "--type=devices", "--action=add"]);
            log!("waiting for udev to settle");
            utils::run_cmd("udevadm", &["settle"]);
            log!("udev is done");
        });
        Some(handle)
    } else {
        log!("unable to find udevd, skip udev.");
        None
    }
}

fn get_guest_tools_dir() -> Option<String> {
    Some(
        env::current_exe()
            .ok()?
            .parent()?
            .parent()?
            .to_str()?
            .to_string(),
    )
}

fn _get_network_devices_from_entries(entries: std::fs::ReadDir) -> Vec<Option<String>> {
    let mut vec = Vec::new();

    // .flatten() ignores lines with reading errors
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        if let Ok(net_entries) = std::fs::read_dir(path.join("net")) {
            // .flatten() ignores lines with reading errors
            if let Some(entry) = net_entries.flatten().next() {
                if let Some(fname) = entry.path().file_name() {
                    vec.push(Some(fname.to_string_lossy().to_string()));
                }
            }
        }
    }
    vec
}

fn get_network_devices() -> Vec<Option<String>> {
    let virtio_net_dir = "/sys/bus/virtio/drivers/virtio_net";
    loop {
        match std::fs::read_dir(virtio_net_dir) {
            Ok(entries) => {
                return _get_network_devices_from_entries(entries);
            }
            Err(_) => {
                // Wait a bit to make sure virtio-net is properly registered in the system.
                thread::sleep(Duration::from_secs_f32(0.25));
            }
        }
    }
}

fn get_network_handle(
    network_dev: Option<String>,
    guest_tools_dir: Option<String>,
) -> Option<thread::JoinHandle<()>> {
    let network_dev_str = network_dev.unwrap();
    log!("setting up network device {}", network_dev_str);
    return Some(thread::spawn(move || {
        let args = [
            "udhcpc",
            "-i",
            &network_dev_str,
            "-n",
            "-q",
            "-f",
            "-s",
            &format!("{}/virtme-udhcpc-script", guest_tools_dir.unwrap()),
        ];
        utils::run_cmd("busybox", &args);
    }));
}

fn setup_network_lo() -> Option<thread::JoinHandle<()>> {
    return Some(thread::spawn(move || {
        utils::run_cmd("ip", &["link", "set", "dev", "lo", "up"]);
    }));
}

fn setup_network() -> Vec<Option<thread::JoinHandle<()>>> {
    let mut vec = vec![setup_network_lo()];

    let cmdline = std::fs::read_to_string("/proc/cmdline").unwrap();
    if cmdline.contains("virtme.dhcp") {
        // Make sure all GIDs are allowed to create raw ICMP sockets (this allows to run ping as
        // regular user).
        if let Ok(mut file) = OpenOptions::new()
            .write(true)
            .open("/proc/sys/net/ipv4/ping_group_range")
        {
            let _ = file.write_all("0 2147483647".as_bytes());
        }

        if let Some(guest_tools_dir) = get_guest_tools_dir() {
            get_network_devices().into_iter().for_each(|network_dev| {
                vec.push(get_network_handle(
                    network_dev,
                    Some(guest_tools_dir.to_owned()),
                ));
            });
        }
    }
    vec
}

fn extract_user_script(virtme_script: &str) -> Option<String> {
    let start_marker = "virtme.exec=`";
    let end_marker = '`';

    let (_before, remaining) = virtme_script.split_once(start_marker)?;
    let (encoded_cmd, _after) = remaining.split_once(end_marker)?;
    String::from_utf8(BASE64.decode(encoded_cmd).ok()?).ok()
}

fn run_user_script(uid: u32) {
    if !std::path::Path::new("/dev/virtio-ports/virtme.stdin").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.stdout").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.stderr").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.dev_stdout").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.dev_stderr").exists()
    {
        log!("virtme-init: cannot find script I/O ports; make sure virtio-serial is available",);
    } else {
        // Re-create stdout/stderr to connect to the virtio-serial ports.
        let io_files = [
            ("/dev/virtio-ports/virtme.ret", "/dev/virtme.ret"),
            ("/dev/virtio-ports/virtme.dev_stdin", "/dev/stdin"),
            ("/dev/virtio-ports/virtme.dev_stdout", "/dev/stdout"),
            ("/dev/virtio-ports/virtme.dev_stderr", "/dev/stderr"),
        ];
        for (src, dst) in io_files.iter() {
            if !std::path::Path::new(src).exists() {
                continue;
            }
            if std::path::Path::new(dst).exists() {
                utils::do_unlink(dst);
            }
            utils::do_chown(src, uid, None).ok();
            utils::do_symlink(src, dst);
        }

        // Detach the process from the controlling terminal
        let open_tty =
            |path| open(path, OFlag::O_RDWR, Mode::empty()).expect("failed to open console.");
        let tty_in = open_tty("/dev/virtio-ports/virtme.stdin");
        let tty_out = open_tty("/dev/virtio-ports/virtme.stdout");
        let tty_err = open_tty("/dev/virtio-ports/virtme.stderr");

        // Determine if we need to switch to a different user, or if we can run the script as root.
        let user = env::var("virtme_user").unwrap_or_else(|_| String::new());
        let (cmd, args) = if !user.is_empty() {
            ("su", vec![user.as_str(), "-c", USER_SCRIPT])
        } else {
            ("/bin/sh", vec![USER_SCRIPT])
        };
        clear_virtme_envs();
        unsafe {
            let ret = Command::new(cmd)
                .args(&args)
                .pre_exec(move || {
                    nix::libc::setsid();
                    libc::close(libc::STDIN_FILENO);
                    libc::close(libc::STDOUT_FILENO);
                    libc::close(libc::STDERR_FILENO);
                    // Make stdin a controlling tty.
                    let stdin_fd = libc::dup2(tty_in, libc::STDIN_FILENO);
                    nix::libc::ioctl(stdin_fd, libc::TIOCSCTTY, 1);
                    libc::dup2(tty_out, libc::STDOUT_FILENO);
                    libc::dup2(tty_err, libc::STDERR_FILENO);
                    Ok(())
                })
                .output()
                .expect("Failed to execute script");

            // Channel the return code to the host via /dev/virtme.ret
            if let Ok(mut file) = OpenOptions::new().write(true).open("/dev/virtme.ret") {
                // Write the value of output.status.code() to the file
                if let Some(code) = ret.status.code() {
                    file.write_all(code.to_string().as_bytes())
                        .expect("Failed to write to file");
                } else {
                    // Handle the case where output.status.code() is None
                    file.write_all(b"-1").expect("Failed to write to file");
                }
            }
        }
        poweroff();
    }
}

fn create_user_script(cmd: &str) {
    utils::create_file(USER_SCRIPT, 0o0755, cmd).expect("Failed to create virtme-script file");
}

fn setup_user_script(uid: u32) {
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if let Some(cmd) = extract_user_script(&cmdline) {
            create_user_script(&cmd);
            if env::var("virtme_graphics").is_err() {
                run_user_script(uid);
            }
        }
    }
}

fn setup_root_home() {
    // Set up a basic environment (unless virtme-ng is running as root on the host)
    if env::var("virtme_root_user").is_err() {
        utils::do_mkdir("/run/tmp/roothome");
        utils::do_mount("/run/tmp/roothome", "/root", "", libc::MS_BIND as usize, "");
        env::set_var("HOME", "/run/tmp/roothome");
    } else {
        env::set_var("HOME", "/root");
    }
}

fn clear_virtme_envs() {
    // Parameters that start with virtme_* shouldn't pollute the environment.
    for (key, _) in env::vars() {
        if key.starts_with("virtme_") {
            env::remove_var(key);
        }
    }
}

// Redirect a file descriptor to another.
fn redirect_fd(src_fd: i32, dst_fd: i32) {
    unsafe {
        libc::dup2(src_fd, dst_fd);
    }
}

// Redirect stdout/stderr to a new console device.
fn redirect_console(consdev: &str) {
    let file = OpenOptions::new()
        .write(true)
        .open(consdev)
        .expect("Failed to open console device");

    let fd = file.into_raw_fd();

    let stdout = std::io::stdout();
    let handle = stdout.lock();
    let stdout_fd = handle.as_raw_fd();
    redirect_fd(fd, stdout_fd);

    let stderr = std::io::stderr();
    let handle = stderr.lock();
    let stderr_fd = handle.as_raw_fd();
    redirect_fd(fd, stderr_fd);
}

fn configure_terminal(consdev: &str, uid: u32) {
    // Set proper user ownership on the default console device
    utils::do_chown(&consdev, uid, None).ok();

    // Redirect stdout/stderr to the new console device.
    redirect_console(&consdev);

    if let Ok(params) = env::var("virtme_stty_con") {
        let output = Command::new("stty")
            .args(params.split_whitespace())
            .stdin(std::fs::File::open(consdev).unwrap())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            // Replace the current init process with a shell session.
            .output();
        log!("{}", String::from_utf8_lossy(&output.unwrap().stderr));
    }
}

fn detach_from_terminal(tty_fd: libc::c_int) {
    // Detach the process from the controlling terminal
    unsafe {
        nix::libc::setsid();
        libc::close(libc::STDIN_FILENO);
        libc::close(libc::STDOUT_FILENO);
        libc::close(libc::STDERR_FILENO);
        let stdin_fd = libc::dup2(tty_fd, libc::STDIN_FILENO);
        nix::libc::ioctl(stdin_fd, libc::TIOCSCTTY, 1);
        libc::dup2(tty_fd, libc::STDOUT_FILENO);
        libc::dup2(tty_fd, libc::STDERR_FILENO);
    }
}

fn run_shell(tty_fd: libc::c_int, args: &[&str]) {
    unsafe {
        Command::new("bash")
            .args(args)
            .pre_exec(move || {
                detach_from_terminal(tty_fd);
                Ok(())
            })
            .output()
            .expect("Failed to start shell session");
    }
}

fn run_user_gui(tty_fd: libc::c_int) {
    // Generate a bare minimum xinitrc
    let xinitrc = "/run/tmp/.xinitrc";

    // Check if we need to start the sound system.
    let mut pre_exec_cmd: String = String::new();
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if cmdline.contains("virtme.sound") {
            if let Some(guest_tools_dir) = get_guest_tools_dir() {
                pre_exec_cmd = format!("{}/virtme-sound-script", guest_tools_dir);
            }
        }
    }
    if let Err(err) = utils::create_file(
        xinitrc,
        0o0644,
        &format!("{}\n/bin/bash {}", pre_exec_cmd, USER_SCRIPT),
    ) {
        log!("failed to generate {}: {}", xinitrc, err);
        return;
    }

    // Run graphical app using xinit directly
    let mut args = vec!["-l", "-c"];
    let storage;
    if let Ok(user) = env::var("virtme_user") {
        // Try to fix permissions on the virtual consoles, we are starting X
        // directly here so we may need extra permissions on the tty devices.
        utils::run_cmd("bash", &["-c", &format!("chown {} /dev/char/*", user)]);

        // Clean up any previous X11 state.
        utils::run_cmd("bash", &["-c", &"rm -f /tmp/.X11*/* /tmp/.X11-lock"]);

        // Start xinit directly.
        storage = format!("su {} -c 'xinit /run/tmp/.xinitrc'", user);
        args.push(&storage);
    } else {
        args.push("xinit /run/tmp/.xinitrc");
    }
    run_shell(tty_fd, &args);
}

fn init_xdg_runtime_dir(uid: u32) {
    // $XDG_RUNTIME_DIR defines the base directory relative to which user-specific non-essential
    // runtime files and other file objects (such as sockets, named pipes, ...) should be stored.
    let dir = format!("/run/user/{}", uid);
    utils::do_mkdir(&dir);
    utils::do_chown(&dir, uid, None).ok();
    env::set_var("XDG_RUNTIME_DIR", dir);
}

fn run_user_shell(tty_fd: libc::c_int) {
    let mut args = vec!["-l"];
    let storage;
    if let Ok(user) = env::var("virtme_user") {
        args.push("-c");
        storage = format!("su {}", user);
        args.push(&storage);
    }
    print_logo();
    run_shell(tty_fd, &args);
}

fn run_user_session(consdev: &str, uid: u32) {
    let flags = OFlag::O_RDWR | OFlag::O_NONBLOCK;
    let mode = Mode::empty();
    let tty_fd = open(consdev, flags, mode).expect("failed to open console");

    setup_user_script(uid);

    if env::var("virtme_graphics").is_ok() {
        run_user_gui(tty_fd);
    } else {
        run_user_shell(tty_fd);
    }
}

fn setup_user_session() {
    let uid = env::var("virtme_user")
        .ok()
        .and_then(|user| utils::get_user_id(&user))
        .unwrap_or(0);

    let consdev = match get_active_console() {
        Some(console) => console,
        None => {
            log!("failed to determine console");
            let err = Command::new("bash").arg("-l").exec();
            log!("failed to exec bash: {}", err);
            return;
        }
    };
    configure_terminal(consdev.as_str(), uid);
    init_xdg_runtime_dir(uid);
    setup_root_home();

    log!("initialization done");

    run_user_session(consdev.as_str(), uid);
}

fn run_sshd() {
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if cmdline.contains("virtme.ssh") {
            if let Some(guest_tools_dir) = get_guest_tools_dir() {
                utils::run_cmd(format!("{}/virtme-sshd-script", guest_tools_dir), &[]);
            }
        }
    }
}

fn run_snapd() {
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if cmdline.contains("virtme.snapd") {
            // If snapd is present in the system try to start it, to properly support snaps.
            let snapd_bin = "/usr/lib/snapd/snapd";
            if !Path::new(snapd_bin).exists() {
                return;
            }
            let snapd_state = "/var/lib/snapd/state.json";
            if !Path::new(snapd_state).exists() {
                return;
            }
            if let Some(guest_tools_dir) = get_guest_tools_dir() {
                utils::run_cmd(format!("{}/virtme-snapd-script", guest_tools_dir), &[]);
            }
            Command::new(snapd_bin)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .ok();
            let snapd_apparmor_bin = "/usr/lib/snapd/snapd-apparmor";
            if Path::new(snapd_apparmor_bin).exists() {
                Command::new(snapd_apparmor_bin)
                    .arg("start")
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .output()
                    .ok();
            }
        }
    }
}

fn extract_vsock_exec(cmdline: &str) -> Option<String> {
    let start_marker = "virtme.vsockexec=`";
    let end_marker = '`';

    let (_before, remaining) = cmdline.split_once(start_marker)?;
    let (encoded_cmd, _after) = remaining.split_once(end_marker)?;
    Some(encoded_cmd.to_string())
}

fn setup_socat_console() {
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if let Some(exec) = extract_vsock_exec(&cmdline) {
            thread::spawn(move || {
                log!("setting up vsock proxy executing {}", exec);
                let key = "virtme_vsockmount";
                if let Ok(path) = env::var(&key) {
                    utils::do_mkdir(&path);
                    utils::do_mount(
                        &key.replace('_', "."),
                        &path,
                        "9p",
                        0,
                        "version=9p2000.L,trans=virtio,access=any",
                    );
                }

                let from = "VSOCK-LISTEN:1024,reuseaddr,fork";
                let to = format!("EXEC:\"{}\",pty,stderr,setsid,sigint,sane,echo=0", exec);
                let args = vec![from, &to];
                utils::run_cmd("socat", &args);
            });
        }
    }
}

fn run_misc_services() -> thread::JoinHandle<()> {
    thread::spawn(|| {
        symlink_fds();
        mount_virtme_initmounts();
        fix_packaging_files();
        override_system_files();
        run_sshd();
        run_snapd();
    })
}

fn print_logo() {
    let logo = r#"
          _      _
   __   _(_)_ __| |_ _ __ ___   ___       _ __   __ _
   \ \ / / |  __| __|  _   _ \ / _ \_____|  _ \ / _  |
    \ V /| | |  | |_| | | | | |  __/_____| | | | (_| |
     \_/ |_|_|   \__|_| |_| |_|\___|     |_| |_|\__  |
                                                |___/"#;
    println!("{}", logo.trim_start_matches('\n'));
    println!("   kernel version: {}", get_kernel_version(true));
    println!("   (CTRL+d to exit)\n");
}

fn main() {
    // Make sure to always run as PID 1.
    check_init_pid();

    // Basic system initialization (order is important here).
    configure_environment();
    configure_hostname();
    mount_kernel_filesystems();
    mount_cgroupfs();
    configure_limits();
    mount_virtme_overlays();
    mount_sys_filesystems();
    mount_kernel_modules();
    run_systemd_tmpfiles();

    // Service running in the background for later
    setup_socat_console();

    // Service initialization (some services can be parallelized here).
    let mut handles = vec![run_udevd(), Some(run_misc_services())];
    handles.append(&mut setup_network());

    // Wait for the completion of the detached services.
    for handle in handles.into_iter().flatten() {
        handle.join().unwrap();
    }

    // Start user session (batch or interactive).
    set_cwd();
    setup_user_session();

    // Shutdown the system.
    poweroff();
}
