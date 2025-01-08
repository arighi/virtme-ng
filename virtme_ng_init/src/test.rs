// SPDX-License-Identifier: GPL-3.0

#[test]
fn test_extract_user_script() {
    let input = "other=stuff virtme.exec=`SGVsbG8K` is=ignored";
    assert_eq!(
        super::extract_user_script(input),
        Some("Hello\n".to_string())
    );
}
