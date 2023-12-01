// SPDX-License-Identifier: GPL-3.0

//! virtme-ng-init: generic helper functions
//!
//! Author: Andrea Righi <andrea.righi@canonical.com>

use nix::mount::{mount, MsFlags};
use nix::sys::stat::Mode;
use nix::unistd::{chown, Gid, Uid};
use std::ffi::{CString, OsStr};
use std::fmt::Arguments;
use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs;
use std::os::unix::fs::PermissionsExt;
use std::process::{Command, Stdio};
use users::get_user_by_name;

macro_rules! log {
    ($($arg:tt)*) => {
        $crate::utils::log_impl(std::format_args!($($arg)*))
    };
}

pub fn log_impl(msg: Arguments<'_>) {
    static PREFIX: &str = "<6>virtme-ng-init: ";
    static LOG_LEVEL: &str = "<6>";

    let mut msg = format!("{}{}", PREFIX, msg);

    // Remove all trailing \n
    while msg.ends_with('\n') {
        msg.pop();
    }

    // Was the message empty? If so, do not log anything
    if PREFIX == msg {
        return;
    }

    match OpenOptions::new().write(true).open("/dev/kmsg") {
        Ok(mut file) => {
            msg.push('\n');
            file.write_all(msg.as_bytes()).ok();
        }
        Err(_) => {
            println!(
                "{}",
                msg.strip_prefix(LOG_LEVEL)
                    .expect("The message should always start with the log level")
            );
        }
    }
}

pub fn get_user_id(username: &str) -> Option<u32> {
    Some(get_user_by_name(username)?.uid())
}

pub fn do_chown(path: &str, uid: u32, gid: Option<u32>) -> std::io::Result<()> {
    let gid_option = gid.map(|gid| Gid::from_raw(gid));

    chown(path, Some(Uid::from_raw(uid)), gid_option)
        .map_err(|err| io::Error::new(std::io::ErrorKind::Other, err))?;

    Ok(())
}

pub fn do_mkdir(path: &str) {
    let dmask = Mode::S_IRWXU | Mode::S_IRGRP | Mode::S_IXGRP | Mode::S_IROTH | Mode::S_IXOTH;
    nix::unistd::mkdir(path, dmask).ok();
}

pub fn do_unlink(path: &str) {
    match std::fs::remove_file(path) {
        Ok(_) => (),
        Err(err) => {
            log!("failed to unlink file {}: {}", path, err);
        }
    }
}

fn do_touch(path: &str, mode: u32) {
    fn _do_touch(path: &str, mode: u32) -> std::io::Result<()> {
        let file = File::create(path)?;
        let permissions = std::fs::Permissions::from_mode(mode);
        file.set_permissions(permissions)?;

        Ok(())
    }
    if let Err(err) = _do_touch(path, mode) {
        log!("error creating file: {}", err);
    }
}

pub fn create_file(fname: &str, mode: u32, content: &str) -> io::Result<()> {
    do_touch(fname, mode);
    if !content.is_empty() {
        let mut file = File::create(fname)?;
        file.write_all(content.as_bytes())?;
    }

    Ok(())
}

pub fn do_symlink(src: &str, dst: &str) {
    match fs::symlink(src, dst) {
        Ok(_) => (),
        Err(err) => {
            log!("failed to create symlink {} -> {}: {}", src, dst, err);
        }
    }
}

pub fn do_mount(source: &str, target: &str, fstype: &str, flags: usize, fsdata: &str) {
    let source_cstr = CString::new(source).expect("CString::new failed");
    let fstype_cstr = CString::new(fstype).expect("CString::new failed");
    let fsdata_cstr = CString::new(fsdata).expect("CString::new failed");

    let result = mount(
        Some(source_cstr.as_ref()),
        target,
        Some(fstype_cstr.as_ref()),
        MsFlags::from_bits_truncate(flags.try_into().unwrap()),
        Some(fsdata_cstr.as_ref()),
    );
    if let Err(err) = result {
        if err != nix::errno::Errno::ENOENT {
            log!("mount {} -> {}: {}", source, target, err);
        }
    }
}

pub fn run_cmd(cmd: impl AsRef<OsStr>, args: &[&str]) {
    let output = Command::new(&cmd)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    match output {
        Ok(output) => {
            if !output.stderr.is_empty() {
                log!(
                    "{}",
                    String::from_utf8_lossy(&output.stderr).trim_end_matches('\n')
                );
            }
        }
        Err(_) => {
            log!(
                "WARNING: failed to run: {:?} {}",
                cmd.as_ref(),
                args.join(" ")
            );
        }
    }
}
