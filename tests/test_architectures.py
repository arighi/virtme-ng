"""Tests for architecture names and native guest detection."""

from types import SimpleNamespace

import pytest

from virtme import architectures, qemu_helpers
from virtme.commands import run
from virtme_ng import run as vng_run


def test_arm64_is_an_alias_of_aarch64():
    assert architectures.get("arm64") is architectures.get("aarch64")
    assert architectures.get("arm64").virtmename == "aarch64"


@pytest.mark.parametrize(
    "host, guest",
    [
        ("x86_64", "x86_64"),
        ("aarch64", "aarch64"),
        ("aarch64", "arm64"),
        ("arm64", "aarch64"),
        ("arm64", "arm64"),
        ("ppc64le", "ppc64le"),
        ("s390x", "s390x"),
        ("i386", "i386"),
        ("arm", "arm"),
        ("ppc64", "ppc64"),
        ("riscv64", "riscv64"),
        ("sparc64", "sparc64"),
    ],
)
def test_native_arch(monkeypatch, host, guest):
    monkeypatch.setattr("platform.machine", lambda: host)
    assert architectures.get(guest).is_native()


@pytest.mark.parametrize(
    "host, guest",
    [
        ("x86_64", "aarch64"),
        ("aarch64", "x86_64"),
        ("ppc64le", "ppc64"),
        ("s390x", "x86_64"),
        ("x86_64", "s390x"),
        ("x86_64", "i386"),
        ("aarch64", "arm"),
        ("x86_64", "riscv64"),
        ("x86_64", "sparc64"),
    ],
)
def test_non_native_arch(monkeypatch, host, guest):
    monkeypatch.setattr("platform.machine", lambda: host)
    assert not architectures.get(guest).is_native()


def can_use_microvm(monkeypatch, host, arch="x86_64"):
    monkeypatch.setattr("platform.machine", lambda: host)
    monkeypatch.setattr(run, "can_use_kvm", lambda args: True)
    args = SimpleNamespace(disable_microvm=False, numa=None, arch=arch)
    return run.can_use_microvm(args)


def test_microvm_native_x86_64(monkeypatch):
    assert can_use_microvm(monkeypatch, "x86_64")


def test_microvm_non_native_x86_64(monkeypatch):
    assert not can_use_microvm(monkeypatch, "aarch64")


def test_microvm_other_arch(monkeypatch):
    assert not can_use_microvm(monkeypatch, "aarch64", arch="aarch64")


@pytest.mark.parametrize(
    "files, guest, expected",
    [
        (["x86_64", "native"], "x86_64", "bin/virtme-ng-init-x86_64"),
        (["native"], "x86_64", "bin/virtme-ng-init"),
        (["aarch64"], "arm64", "bin/virtme-ng-init-aarch64"),
        (["native"], "aarch64", "virtme-init"),
        ([], "x86_64", "virtme-init"),
    ],
)
def test_find_virtme_init(tmp_path, monkeypatch, files, guest, expected):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    (tmp_path / "bin").mkdir()
    for name in files:
        suffix = "" if name == "native" else f"-{name}"
        (tmp_path / "bin" / f"virtme-ng-init{suffix}").touch()
    init = run.find_virtme_init(str(tmp_path), architectures.get(guest))
    assert init == expected


@pytest.mark.parametrize(
    "host, qemuname, found",
    [
        ("arm64", "aarch64", "/usr/bin/qemu-kvm"),
        ("x86_64", "aarch64", None),
    ],
)
def test_qemu_kvm_fallback(monkeypatch, host, qemuname, found):
    monkeypatch.setattr("platform.machine", lambda: host)
    which = {"qemu-kvm": "/usr/bin/qemu-kvm"}
    monkeypatch.setattr("shutil.which", which.get)
    is_native = architectures.get(qemuname).is_native()
    if found is None:
        with pytest.raises(ValueError):
            qemu_helpers.Qemu(None, qemuname, is_native)
    else:
        assert qemu_helpers.Qemu(None, qemuname, is_native).qemubin == found


@pytest.mark.parametrize(
    "host, expected",
    [("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64"), ("foo", None)],
)
def test_get_host_arch(monkeypatch, host, expected):
    monkeypatch.setattr("platform.machine", lambda: host)
    assert vng_run.get_host_arch() == expected
