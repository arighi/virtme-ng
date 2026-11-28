// SPDX-License-Identifier: GPL-3.0

#[test]
fn test_extract_user_script() {
    let input = "other=stuff virtme.exec=`SGVsbG8K` is=ignored";
    assert_eq!(
        super::extract_user_script(input),
        Some("Hello\n".to_string())
    );
}

const PROC_NET_DEV: &str = "\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
  eth0:    1234      10    0    0    0     0          0         0      567       8    0    0    0     0       0          0
";

#[test]
fn test_proc_net_dev_lists() {
    assert!(super::proc_net_dev_lists(PROC_NET_DEV, "eth0"));
    assert!(super::proc_net_dev_lists(PROC_NET_DEV, "lo"));
    assert!(!super::proc_net_dev_lists(PROC_NET_DEV, "eth1"));
    assert!(!super::proc_net_dev_lists(PROC_NET_DEV, "eth"));
}

#[test]
fn test_wait_for_interface() {
    let path = std::env::temp_dir().join(format!("virtme-ng-init-test-{}", std::process::id()));
    std::fs::write(&path, PROC_NET_DEV).unwrap();
    let zero = std::time::Duration::ZERO;
    assert!(super::wait_for_interface(&path, "eth0", zero));
    assert!(!super::wait_for_interface(&path, "eth1", zero));
    std::fs::remove_file(&path).unwrap();
}
