// SPDX-License-Identifier: GPL-3.0

//! virtme-ng-init: generic helper functions
//!
//! Author: Andrea Righi <andrea.righi@canonical.com>

use nix::libc;
use nix::mount::{mount, MsFlags};
use nix::sys::stat::Mode;
use nix::unistd::{chown, Gid, Uid};
use std::ffi::CString;
use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs;
use std::os::unix::fs::PermissionsExt;
use std::process::{Command, Stdio};
use users::get_user_by_name;

static PROG_NAME: &'static str = "virtme-ng-init";

pub fn log(msg: &str) {
    if msg.is_empty() {
        return;
    }
    let msg = format!("{}: {}", PROG_NAME, msg.trim_end_matches('\n'));
    let mut file = OpenOptions::new().write(true).open("/dev/kmsg").ok();
    match &mut file {
        Some(file) => {
            let msg = format!("<6>{}\n", msg);
            file.write(msg.as_bytes()).ok();
        }
        None => {
            println!("{}", msg);
        }
    }
}

pub fn get_user_id(username: &str) -> Option<u32> {
    if let Some(user) = get_user_by_name(username) {
        return Some(user.uid());
    }
    None
}

pub fn do_chown(path: &str, uid: u32, gid: u32) -> io::Result<()> {
    chown(path, Some(Uid::from_raw(uid)), Some(Gid::from_raw(gid)))
        .map_err(|err| io::Error::new(io::ErrorKind::Other, err))?;

    Ok(())
}

pub fn do_mkdir(path: &str) {
    let dmask = libc::S_IRWXU | libc::S_IRGRP | libc::S_IXGRP | libc::S_IROTH | libc::S_IXOTH;
    nix::unistd::mkdir(path, Mode::from_bits_truncate(dmask as u32)).ok();
}

pub fn do_unlink(path: &str) {
    match std::fs::remove_file(path) {
        Ok(_) => (),
        Err(err) => {
            log(&format!("failed to unlink file {}: {}", path, err));
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
        log(&format!("error creating file: {}", err));
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
            log(&format!(
                "failed to create symlink {} -> {}: {}",
                src, dst, err
            ));
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
        log(&format!(
            "mount {} -> {}: {}",
            source,
            target,
            err.to_string()
        ));
    }
}

pub fn run_cmd(cmd: &str, args: &[&str]) {
    let output = Command::new(cmd)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    match output {
        Ok(output) => {
            if !output.stderr.is_empty() {
                log(String::from_utf8_lossy(&output.stderr).trim_end_matches('\n'));
            }
        }
        Err(_) => {
            log(&format!(
                "WARNING: failed to run: {} {}",
                cmd,
                args.join(" ")
            ));
        }
    }
}
