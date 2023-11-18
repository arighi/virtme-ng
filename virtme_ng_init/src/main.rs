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

use libc::{uname, utsname};
use nix::fcntl::{open, OFlag};
use nix::libc;
use nix::sys::reboot;
use nix::sys::stat::Mode;
use nix::unistd::sethostname;
use std::env;
use std::ffi::CStr;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::mem;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{exit, id, Command, Stdio};
use std::thread;
use std::time::Duration;
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
        source: "tmpfs",
        target: "/tmp",
        fs_type: "tmpfs",
        flags: 0,
        fsdata: "",
    },
    MountInfo {
        source: "run",
        target: "/run",
        fs_type: "tmpfs",
        flags: 0,
        fsdata: "",
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
    MountInfo {
        source: "cgroup2",
        target: "/sys/fs/cgroup",
        fs_type: "cgroup2",
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

const USER_SCRIPT: &str = "/tmp/.virtme-script";

fn check_init_pid() {
    if id() != 1 {
        utils::log(&format!("must be run as PID 1"));
        exit(1);
    }
}

fn poweroff() {
    unsafe {
        libc::sync();
    }
    if let Err(err) = reboot::reboot(reboot::RebootMode::RB_POWER_OFF) {
        utils::log(&format!("error powering off: {}", err));
        exit(1);
    }
    exit(0);
}

fn configure_environment() {
    env::set_var("PATH", "/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin");
}

fn get_kernel_version(show_machine: bool) -> String {
    unsafe {
        let mut utsname: utsname = mem::zeroed();
        if uname(&mut utsname) == -1 {
            return String::from("None");
        }
        let release = CStr::from_ptr(utsname.release.as_ptr())
            .to_string_lossy()
            .into_owned();
        if show_machine {
            let machine = CStr::from_ptr(utsname.machine.as_ptr())
                .to_string_lossy()
                .into_owned();
            format!("{} {}", release, machine)
        } else {
            release
        }
    }
}

fn get_active_console() -> Option<String> {
    // See Documentation/filesystems/proc.rst for /proc/consoles documentation.
    match File::open("/proc/consoles") {
        Ok(file) => {
            let reader = BufReader::new(file);

            for line in reader.lines() {
                if let Ok(line) = line {
                    if line.chars().nth(27) == Some('C') {
                        let console = line.split(' ').next()?.to_string();
                        return Some(format!("/dev/{}", console));
                    }
                }
            }
            None
        }
        Err(error) => {
            utils::log(&format!("failed to open /proc/consoles: {}", error));
            None
        }
    }
}

fn configure_hostname() {
    if let Ok(hostname) = env::var("virtme_hostname") {
        if let Err(err) = sethostname(hostname) {
            utils::log(&format!("failed to change hostname: {}", err));
        }
    } else {
        utils::log(&format!("virtme_hostname is not defined"));
    }
}

fn run_systemd_tmpfiles() {
    let args: &[&str] = &[
        "--create",
        "--boot",
        "--exclude-prefix=/dev",
        "--exclude-prefix=/root",
    ];
    utils::run_cmd("systemd-tmpfiles", args);
}

fn generate_fstab() -> io::Result<()> {
    utils::create_file("/tmp/fstab", 0o0664, "").ok();
    utils::do_mount("/tmp/fstab", "/etc/fstab", "", libc::MS_BIND as usize, "");
    Ok(())
}

fn generate_shadow() -> io::Result<()> {
    utils::create_file("/tmp/shadow", 0o0644, "").ok();

    let input_file = File::open("/etc/passwd")?;
    let output_file = File::create("/tmp/shadow")?;

    let reader = BufReader::new(input_file);
    let mut writer = BufWriter::new(output_file);

    for line in reader.lines() {
        let line = line?;
        let parts: Vec<&str> = line.split(':').collect();

        if !parts.is_empty() {
            let username = parts[0];
            writeln!(writer, "{}:!:::::::", username)?;
        }
    }
    utils::do_mount("/tmp/shadow", "/etc/shadow", "", libc::MS_BIND as usize, "");

    Ok(())
}

fn generate_sudoers() -> io::Result<()> {
    if let Ok(user) = env::var("virtme_user") {
        let fname = "/tmp/sudoers";
        utils::create_file(fname, 0o0440, "").ok();
        let mut file = File::create(fname)?;
        let content = format!(
            "root ALL = (ALL) NOPASSWD: ALL\n{} ALL = (ALL) NOPASSWD: ALL\n",
            user
        );
        file.write_all(content.as_bytes())?;
        utils::do_mount(fname, "/etc/sudoers", "", libc::MS_BIND as usize, "");
    }
    Ok(())
}

fn override_system_files() {
    generate_fstab().ok();
    generate_shadow().ok();
    generate_sudoers().ok();
}

fn set_cwd() {
    if let Ok(dir) = env::var("virtme_chdir") {
        if let Err(err) = env::set_current_dir(dir) {
            utils::log(&format!("error changing directory: {}", err));
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
        utils::do_mount(
            mount_info.source,
            mount_info.target,
            mount_info.fs_type,
            mount_info.flags,
            mount_info.fsdata,
        )
    }
}

fn mount_virtme_overlays() {
    for (key, path) in env::vars() {
        if key.starts_with("virtme_rw_overlay") {
            let dir = &format!("/tmp/{}", key);
            let upperdir = &format!("{}/upper", dir);
            let workdir = &format!("{}/work", dir);
            let mnt_opts = &format!(
                "xino=off,lowerdir={},upperdir={},workdir={}",
                path, upperdir, workdir
            );
            utils::do_mkdir(dir);
            utils::do_mkdir(upperdir);
            utils::do_mkdir(workdir);
            utils::do_mount(&key, &path, "overlay", 0, mnt_opts);
        }
    }
}

fn mount_virtme_initmounts() {
    for (key, path) in env::vars() {
        if key.starts_with("virtme_initmount") {
            utils::do_mkdir(&path);
            utils::do_mount(
                &key.replace("_", "."),
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
    let lock_files = vec![
        "/var/lib/dpkg/lock",
        "/var/lib/dpkg/lock-frontend",
        "/var/lib/dpkg/triggers/Lock",
    ];
    for path in &lock_files {
        let fname = Path::new(path)
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("");
        if fname.is_empty() {
            continue;
        }
        let src_file = format!("/tmp/{}", fname);
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
        utils::log("you have CONFIG_UEVENT_HELPER on, turn it off");
        let mut file = OpenOptions::new().write(true).open(uevent_helper_path).ok();
        match &mut file {
            Some(file) => {
                write!(file, "").ok();
            }
            None => {
                utils::log(&format!("error opening {}", uevent_helper_path));
            }
        }
    }
}

fn find_udevd() -> Option<PathBuf> {
    let mut udevd = PathBuf::new();

    if PathBuf::from("/usr/lib/systemd/systemd-udevd").exists() {
        udevd = PathBuf::from("/usr/lib/systemd/systemd-udevd");
    } else if PathBuf::from("/lib/systemd/systemd-udevd").exists() {
        udevd = PathBuf::from("/lib/systemd/systemd-udevd");
    } else if let Ok(path) = env::var("PATH") {
        for dir in path.split(':') {
            let udevd_path = PathBuf::from(dir).join("udevd");
            if udevd_path.exists() {
                udevd = udevd_path;
                break;
            }
        }
    }
    if udevd.exists() {
        Some(udevd)
    } else {
        None
    }
}

fn run_udevd() -> Option<thread::JoinHandle<()>> {
    if let Some(udevd_path) = find_udevd() {
        let handle = thread::spawn(move || {
            disable_uevent_helper();
            let args: &[&str] = &["--daemon", "--resolve-names=never"];
            utils::run_cmd(&udevd_path.to_string_lossy(), args);
            utils::log("triggering udev coldplug");
            utils::run_cmd("udevadm", &["trigger", "--type=subsystems", "--action=add"]);
            utils::run_cmd("udevadm", &["trigger", "--type=devices", "--action=add"]);
            utils::log("waiting for udev to settle");
            utils::run_cmd("udevadm", &["settle"]);
            utils::log("udev is done");
        });
        Some(handle)
    } else {
        utils::log("unable to find udevd, skip udev.");
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

fn _get_network_device_from_entries(entries: std::fs::ReadDir) -> Option<String> {
    for entry in entries {
        if let Ok(entry) = entry {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            if let Ok(net_entries) = std::fs::read_dir(path.join("net")) {
                for entry in net_entries {
                    if let Ok(entry) = entry {
                        let path = entry.path().file_name()?.to_string_lossy().to_string();
                        return Some(path);
                    }
                }
            }
        }
    }
    return None;
}

fn get_network_device() -> Option<String> {
    let virtio_net_dir = "/sys/bus/virtio/drivers/virtio_net";
    loop {
        match std::fs::read_dir(virtio_net_dir) {
            Ok(entries) => {
                return _get_network_device_from_entries(entries);
            }
            Err(_) => {
                // Wait a bit to make sure virtio-net is properly registered in the system.
                thread::sleep(Duration::from_secs_f32(0.25));
            }
        }
    }
}

fn setup_network() -> Option<thread::JoinHandle<()>> {
    utils::run_cmd("ip", &["link", "set", "dev", "lo", "up"]);
    let cmdline = std::fs::read_to_string("/proc/cmdline").ok()?;
    if cmdline.contains("virtme.dhcp") {
        if let Some(guest_tools_dir) = get_guest_tools_dir() {
            if let Some(network_dev) = get_network_device() {
                utils::log(&format!("setting up network device {}", network_dev));
                let handle = thread::spawn(move || {
                    let args = [
                        "udhcpc",
                        "-i",
                        &network_dev,
                        "-n",
                        "-q",
                        "-f",
                        "-s",
                        &format!("{}/virtme-udhcpc-script", guest_tools_dir),
                    ];
                    utils::run_cmd("busybox", &args);
                });
                return Some(handle);
            }
        }
    }
    None
}

fn extract_user_script(virtme_script: &str) -> Option<String> {
    let start_marker = "virtme.exec=`";
    let end_marker = '`';

    let (_before, remaining) = virtme_script.split_once(start_marker)?;
    let (encoded_cmd, _after) = remaining.split_once(end_marker)?;
    Some(String::from_utf8(BASE64.decode(encoded_cmd).ok()?).ok()?)
}

fn run_user_script() {
    if !std::path::Path::new("/dev/virtio-ports/virtme.stdin").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.stdout").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.stderr").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.dev_stdout").exists()
        || !std::path::Path::new("/dev/virtio-ports/virtme.dev_stderr").exists()
    {
        utils::log(
            "virtme-init: cannot find script I/O ports; make sure virtio-serial is available",
        );
    } else {
        // Re-create stdout/stderr to connect to the virtio-serial ports.
        let io_files = [
            ("/dev/virtio-ports/virtme.dev_stdin", "/dev/stdin"),
            ("/dev/virtio-ports/virtme.dev_stdout", "/dev/stdout"),
            ("/dev/virtio-ports/virtme.dev_stderr", "/dev/stderr"),
        ];
        for (src, dst) in io_files.iter() {
            if std::path::Path::new(dst).exists() {
                utils::do_unlink(dst);
            }
            utils::do_symlink(src, dst);
        }

        // Detach the process from the controlling terminal
        let flags = libc::O_RDWR;
        let mode = Mode::empty();
        let tty_in = open(
            "/dev/virtio-ports/virtme.stdin",
            OFlag::from_bits_truncate(flags),
            mode,
        )
        .expect("failed to open console.");
        let tty_out = open(
            "/dev/virtio-ports/virtme.stdout",
            OFlag::from_bits_truncate(flags),
            mode,
        )
        .expect("failed to open console.");
        let tty_err = open(
            "/dev/virtio-ports/virtme.stderr",
            OFlag::from_bits_truncate(flags),
            mode,
        )
        .expect("failed to open console.");

        // Determine if we need to switch to a different user, or if we can run the script as root.
        let cmd: String;
        let args: Vec<&str>;
        let user: String;
        if let Ok(virtme_user) = env::var("virtme_user") {
            user = virtme_user;
        } else {
            user = String::new();
        }
        if !user.is_empty() {
            cmd = "su".to_string();
            args = vec![&user, "-c", USER_SCRIPT];
        } else {
            cmd = "/bin/sh".to_string();
            args = vec![USER_SCRIPT];
        }
        clear_virtme_envs();
        unsafe {
            Command::new(&cmd)
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
        }
        poweroff();
    }
}

fn create_user_script(cmd: &str) {
    utils::create_file(USER_SCRIPT, 0o0755, cmd).expect("Failed to create virtme-script file");
}

fn setup_user_script() {
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if let Some(cmd) = extract_user_script(&cmdline) {
            create_user_script(&cmd);
            if env::var("virtme_graphics").is_err() {
                run_user_script();
            }
        }
    }
}

fn setup_root_home() {
    utils::do_mkdir("/tmp/roothome");
    utils::do_mount("/tmp/roothome", "/root", "", libc::MS_BIND as usize, "");
    env::set_var("HOME", "/tmp/roothome");
}

fn clear_virtme_envs() {
    // Parameters that start with virtme_* shouldn't pollute the environment.
    for (key, _) in env::vars() {
        if key.starts_with("virtme_") {
            env::remove_var(key);
        }
    }
}

fn configure_terminal(consdev: &str) {
    if let Ok(params) = env::var("virtme_stty_con") {
        let output = Command::new("stty")
            .args(params.split_whitespace())
            .stdin(std::fs::File::open(consdev).unwrap())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            // Replace the current init process with a shell session.
            .output();
        utils::log(String::from_utf8_lossy(&output.unwrap().stderr).trim_end_matches('\n'));
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

fn run_shell(tty_fd: libc::c_int, args: Vec<String>) {
    unsafe {
        Command::new("bash")
            .args(args.into_iter())
            .pre_exec(move || {
                detach_from_terminal(tty_fd);
                Ok(())
            })
            .output()
            .expect("Failed to start shell session");
    }
}

fn init_xdg_runtime_dir() {
    // Initialize XDG_RUNTIME_DIR (required to provide a better compatibility with graphic apps).
    let mut uid = 0;
    if let Ok(user) = env::var("virtme_user") {
        if let Some(virtme_uid) = utils::get_user_id(&user) {
            uid = virtme_uid;
        }
    }
    let dir = format!("/run/user/{}", uid);
    utils::do_mkdir(&dir);
    utils::do_chown(&dir, uid, uid).ok();
    env::set_var("XDG_RUNTIME_DIR", dir);
}

fn run_user_gui(tty_fd: libc::c_int) {
    init_xdg_runtime_dir();

    // Generate a bare minimum xinitrc
    let xinitrc = "/tmp/.xinitrc";

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
        utils::log(&format!("failed to generate {}: {}", xinitrc, err));
        return;
    }

    // Run graphical app using xinit directly
    let mut args: Vec<String> = vec!["-l".to_owned(), "-c".to_owned()];
    if let Ok(user) = env::var("virtme_user") {
        // Try to fix permissions on the virtual consoles, we are starting X
        // directly here so we may need extra permissions on the tty devices.
        utils::run_cmd("bash", &["-c", &format!("chown {} /dev/char/*", user)]);

        // Start xinit directly.
        args.push(format!("su {} -c 'xinit /tmp/.xinitrc'", user));
    } else {
        args.push("xinit /tmp/.xinitrc".to_owned());
    }
    run_shell(tty_fd, args);
}

fn run_user_shell(tty_fd: libc::c_int) {
    let mut args: Vec<String> = vec!["-l".to_owned()];
    if let Ok(user) = env::var("virtme_user") {
        args.push("-c".to_owned());
        args.push(format!("su {}", user));
    }
    run_shell(tty_fd, args);
}

fn run_user_session() {
    let consdev = match get_active_console() {
        Some(console) => console,
        None => {
            utils::log("failed to determine console");
            Command::new("bash").arg("-l").exec();
            return;
        }
    };
    configure_terminal(consdev.as_str());

    let flags = libc::O_RDWR | libc::O_NONBLOCK;
    let mode = Mode::empty();
    let tty_fd = open(consdev.as_str(), OFlag::from_bits_truncate(flags), mode)
        .expect("failed to open console");

    if let Ok(_) = env::var("virtme_graphics") {
        run_user_gui(tty_fd);
    } else {
        run_user_shell(tty_fd);
    }
}

fn setup_user_session() {
    utils::log("initialization done");
    print_logo();
    setup_root_home();
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
                utils::run_cmd(&format!("{}/virtme-snapd-script", guest_tools_dir), &[]);
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

fn run_misc_services() -> thread::JoinHandle<()> {
    thread::spawn(|| {
        symlink_fds();
        mount_virtme_initmounts();
        fix_packaging_files();
        override_system_files();
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
    println!("{}", logo.trim_start_matches("\n"));
    println!("   kernel version: {}\n", get_kernel_version(true));
}

fn main() {
    // Make sure to always run as PID 1.
    check_init_pid();

    // Basic system initialization (order is important here).
    configure_environment();
    configure_hostname();
    mount_kernel_filesystems();
    mount_virtme_overlays();
    mount_sys_filesystems();
    mount_kernel_modules();
    run_systemd_tmpfiles();

    // Service initialization (some services can be parallelized here).
    let mut handles: Vec<Option<thread::JoinHandle<()>>> = Vec::new();
    handles.push(run_udevd());
    handles.push(setup_network());
    handles.push(Some(run_misc_services()));

    // Wait for the completion of the detached services.
    for handle in handles.into_iter().flatten() {
        handle.join().unwrap();
    }

    // Start user session (batch or interactive).
    set_cwd();
    setup_user_script();
    setup_user_session();
    run_user_session();

    // Shutdown the system.
    poweroff();
}
