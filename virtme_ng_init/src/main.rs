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

use libc::{uname, utsname};
use nix::fcntl::{open, OFlag};
use nix::libc;
use nix::sys::reboot;
use nix::sys::stat::Mode;
use nix::unistd::sethostname;
use std::collections::HashMap;
use std::env;
use std::ffi::CStr;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::mem;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{exit, id, Command, Stdio};
use std::thread;
mod utils;

struct MountInfo {
    source: &'static str,
    target: &'static str,
    fs_type: &'static str,
    flags: u64,
    fsdata: &'static str,
}

const KERNEL_MOUNTS: &[MountInfo] = &[
    MountInfo {
        source: "sys",
        target: "/sys",
        fs_type: "sysfs",
        flags: libc::MS_NOSUID | libc::MS_NOEXEC | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "proc",
        target: "/proc",
        fs_type: "proc",
        flags: libc::MS_NOSUID | libc::MS_NOEXEC | libc::MS_NODEV,
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
        source: "devtmpfs",
        target: "/dev",
        fs_type: "devtmpfs",
        flags: libc::MS_NOSUID | libc::MS_NOEXEC,
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
        flags: libc::MS_NOSUID | libc::MS_NOEXEC,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/dev/shm",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/log",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/tmp",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/spool/rsyslog",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/portables",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/machines",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/private",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/lib/apt",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
    MountInfo {
        source: "tmpfs",
        target: "/var/cache",
        fs_type: "tmpfs",
        flags: libc::MS_NOSUID | libc::MS_NODEV,
        fsdata: "",
    },
];

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
    utils::do_touch("/tmp/fstab", 0o0664);
    utils::do_mount("/tmp/fstab", "/etc/fstab", "", libc::MS_BIND, "");
    Ok(())
}

fn generate_shadow() -> io::Result<()> {
    utils::do_touch("/tmp/shadow", 0o0644);

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
    utils::do_mount("/tmp/shadow", "/etc/shadow", "", libc::MS_BIND, "");

    Ok(())
}

fn generate_sudoers() -> io::Result<()> {
    if let Ok(user) = env::var("virtme_user") {
        let fname = "/tmp/sudoers";
        utils::do_touch(fname, 0o0440);
        let mut file = File::create(fname)?;
        let content = format!(
            "root ALL = (ALL) NOPASSWD: ALL\n{} ALL = (ALL) NOPASSWD: ALL\n",
            user
        );
        file.write_all(content.as_bytes())?;
        utils::do_mount(fname, "/etc/sudoers", "", libc::MS_BIND, "");
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
    let fd_links: HashMap<&str, &str> = vec![
        ("/proc/self/fd", "/dev/fd"),
        ("/proc/self/fd/0", "/dev/stdin"),
        ("/proc/self/fd/1", "/dev/stdout"),
        ("/proc/self/fd/2", "/dev/stderr"),
    ]
    .into_iter()
    .collect();

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
        utils::do_touch(&src_file, 0o0640);
        utils::do_mount(&src_file, path, "", libc::MS_BIND, "");
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
    if let Ok(current_exe) = env::current_exe() {
        if let Some(parent_dir) = current_exe.parent() {
            if let Some(dir) = parent_dir.to_str() {
                return Some(dir.to_string());
            }
        }
    }
    None
}

fn get_network_device() -> Option<String> {
    let virtio_net_dir = "/sys/bus/virtio/drivers/virtio_net";
    if let Ok(entries) = std::fs::read_dir(virtio_net_dir) {
        // Sort and get the first entry in this directory
        let mut sorted_entries: Vec<_> = entries
            .filter_map(|entry| entry.ok())
            .map(|entry| entry.path())
            .filter(|path| path.is_dir())
            .collect();
        sorted_entries.sort();

        if let Some(first_entry) = sorted_entries.first() {
            let net_dir = first_entry.join("net");
            if let Ok(net_entries) = std::fs::read_dir(net_dir) {
                if let Some(first_net_entry) = net_entries
                    .filter_map(|entry| entry.ok())
                    .map(|entry| entry.file_name())
                    .filter_map(|name| name.to_str().map(|s| s.to_owned()))
                    .next()
                {
                    return Some(first_net_entry);
                }
            }
        }
    }
    None
}

fn setup_network() -> Option<thread::JoinHandle<()>> {
    utils::run_cmd("ip", &["link", "set", "dev", "lo", "up"]);
    if let Ok(cmdline) = std::fs::read_to_string("/proc/cmdline") {
        if cmdline.contains("virtme.dhcp") {
            if let Some(guest_tools_dir) = get_guest_tools_dir() {
                if let Some(network_device) = get_network_device() {
                    let handle = thread::spawn(move || {
                        let args = [
                            "udhcpc",
                            "-i",
                            &network_device,
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
    }
    None
}

fn run_script() {
    if !utils::is_file_executable("/run/virtme/data/script") {
        return;
    }
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
        let io_files: HashMap<&str, &str> = vec![
            ("/dev/virtio-ports/virtme.dev_stdin", "/dev/stdin"),
            ("/dev/virtio-ports/virtme.dev_stdout", "/dev/stdout"),
            ("/dev/virtio-ports/virtme.dev_stderr", "/dev/stderr"),
        ]
        .into_iter()
        .collect();
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

        clear_virtme_envs();
        unsafe {
            Command::new("/run/virtme/data/script")
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
    }
    poweroff();
}

fn setup_root_home() {
    utils::do_mkdir("/tmp/roothome");
    utils::do_mount("/tmp/roothome", "/root", "", libc::MS_BIND, "");
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

fn run_shell() {
    if let Some(consdev) = get_active_console() {
        configure_terminal(consdev.as_str());

        let flags = libc::O_RDWR | libc::O_NONBLOCK;
        let mode = Mode::empty();
        let tty_fd = open(consdev.as_str(), OFlag::from_bits_truncate(flags), mode)
            .expect("Failed to open console.");

        let mut args: Vec<&str> = vec!["-l"];
        let user_cmd: String;

        if let Ok(user) = env::var("virtme_user") {
            user_cmd = format!("su {}", user);
            args.push("-c");
            args.push(&user_cmd);
        }

        clear_virtme_envs();
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
    } else {
        utils::log("Failed to determine console");
        Command::new("bash").arg("-l").exec();
    }
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

fn start_session() {
    utils::log("initialization done");
    print_logo();
    setup_root_home();
    run_shell();
}

fn run_misc_services() -> Option<thread::JoinHandle<()>> {
    let handle = thread::spawn(move || {
        symlink_fds();
        mount_virtme_initmounts();
        fix_packaging_files();
        override_system_files();
    });
    Some(handle)
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
    handles.push(run_misc_services());

    // Wait for the completion of the detached services.
    for handle in handles.into_iter().flatten() {
        handle.join().unwrap();
    }

    // Start user session (batch or interactive).
    set_cwd();
    run_script();
    start_session();

    // Shutdown the system.
    poweroff();
}
