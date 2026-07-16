# -*- mode: python -*-
# kernel_image: Normalize kernel images for QEMU direct boot
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

"""Helpers to normalize distro kernel images before passing them to QEMU."""

import gzip
import hashlib
import io
import os
import resource
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

GZIP_MAGIC = b"\x1f\x8b"
PE_MSDOS_MAGIC = b"MZ"
PE_SIGNATURE = b"PE\0\0"
ARM64_IMAGE_MAGIC = b"ARM\x64"
ZBOOT_MAGIC = b"zimg"
EFI_PE_LINUX_MAGIC = b"\xcd\x23\x82\x81"

ARM64_IMAGE_MAGIC_OFFSET = 56
# Match QEMU's LOAD_IMAGE_MAX_DECOMPRESSED_BYTES limit used by its arm64 loader.
MAX_DECOMPRESSED_SIZE = 256 * 1024 * 1024

PE_HEADER_OFFSET = 0x3C
PE_SIGNATURE_SIZE = 4
COFF_HEADER_SIZE = 20
SECTION_HEADER_SIZE = 40
SECTION_NAME_SIZE = 8
SECTION_COUNT_OFFSET = 6
OPTIONAL_HEADER_SIZE_OFFSET = 20
SECTION_RAW_SIZE_OFFSET = 16
SECTION_RAW_OFFSET_OFFSET = 20

ZBOOT_HEADER_SIZE = 64
ZBOOT_PAYLOAD_OFFSET = 8
ZBOOT_PAYLOAD_SIZE = 12
ZBOOT_COMPRESSION_TYPE = slice(24, 56)
ZBOOT_LINUX_MAGIC = slice(56, 60)


class KernelImageError(Exception):
    pass


def normalize_kernel_image(arch, path: str, cache_dir: Path, verbose=False) -> str:
    # QEMU's arm64 -kernel path expects the bootloader to hand it a plain Image,
    # but distro kernels may be wrapped as EFI zboot images.
    if getattr(arch, "linuxname", None) != "arm64":
        return path

    image = Path(path)
    try:
        with image.open("rb") as stream:
            header = stream.read(ARM64_IMAGE_MAGIC_OFFSET + len(ARM64_IMAGE_MAGIC))
    except OSError as exc:
        raise KernelImageError(f"failed to read kernel image {image}: {exc}") from exc

    # Avoid reading and hashing the complete file in the common case where QEMU
    # can consume an already-plain arm64 Image directly.
    if _is_arm64_image(header):
        return path

    output = _cached_image_path(cache_dir, image)
    if output.is_file():
        if verbose:
            print(
                f"virtme: using normalized arm64 kernel image {output}",
                file=sys.stderr,
            )
        return str(output)

    try:
        data = image.read_bytes()
    except OSError as exc:
        raise KernelImageError(f"failed to read kernel image {image}: {exc}") from exc

    # The image may have been replaced after the streaming hash above. Derive
    # the publication path from the exact bytes that will be normalized so the
    # cache remains content-addressed. This also notices a cache entry published
    # by a concurrent invocation after the first lookup.
    output = _cached_image_path_from_digest(cache_dir, hashlib.sha256(data).hexdigest())
    if output.is_file():
        if verbose:
            print(
                f"virtme: using normalized arm64 kernel image {output}",
                file=sys.stderr,
            )
        return str(output)

    if not _prepare_arm64_image(data, image, output):
        return path

    if verbose:
        print(f"virtme: using normalized arm64 kernel image {output}", file=sys.stderr)
    return str(output)


def _prepare_arm64_image(data: bytes, image: Path, output: Path) -> bool:
    work = _gunzip_if_needed(data, image)
    linux_section = _pe_section(work, b".linux")
    if linux_section is not None:
        work = _gunzip_if_needed(linux_section, image)
        if _is_arm64_image(work):
            if not output.exists():
                _write_atomic(output, work)
            return True
    elif _is_arm64_image(work):
        return False

    zboot = _parse_zboot(work)
    if zboot is None:
        if linux_section is not None or _is_pe_image(work):
            sys.stderr.write(
                f"virtme: warning: {image} looks like an EFI application "
                "that could not be normalized; QEMU -kernel may not boot it\n"
            )
        return False

    compression, payload = zboot
    if compression == "gzip":
        try:
            prepared = _decompress_gzip(payload, image)
        except (EOFError, OSError) as exc:
            raise KernelImageError(
                f"failed to decompress arm64 EFI zboot image {image}: {exc}"
            ) from exc
        if not output.exists():
            _write_atomic(output, prepared)
        return True
    if compression == "zstd":
        if not output.exists():
            _decompress_zstd(payload, image, output)
        return True
    if compression in ("", "none"):
        if not output.exists():
            _write_atomic(output, payload)
        return True

    raise KernelImageError(
        f"unsupported arm64 EFI zboot compression in {image}: {compression}"
    )


def _gunzip_if_needed(data: bytes, image: Path) -> bytes:
    if not data.startswith(GZIP_MAGIC):
        return data

    try:
        return _decompress_gzip(data, image)
    except (EOFError, OSError):
        return data


def _decompress_gzip(data: bytes, image: Path) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        # Read one byte past the limit to distinguish an exact-size image from
        # an oversized one without decompressing the rest of the input.
        output = stream.read(MAX_DECOMPRESSED_SIZE + 1)
    if len(output) > MAX_DECOMPRESSED_SIZE:
        raise _decompressed_image_too_large(image)
    return output


def _pe_header_offset(data: bytes) -> int | None:
    if len(data) < 0x40 or not data.startswith(PE_MSDOS_MAGIC):
        return None

    pe_offset = _u32(data, PE_HEADER_OFFSET)
    if pe_offset is None or pe_offset + PE_SIGNATURE_SIZE + COFF_HEADER_SIZE > len(
        data
    ):
        return None
    if data[pe_offset : pe_offset + PE_SIGNATURE_SIZE] != PE_SIGNATURE:
        return None
    return pe_offset


def _is_pe_image(data: bytes) -> bool:
    return _pe_header_offset(data) is not None


def _is_arm64_image(data: bytes) -> bool:
    magic_end = ARM64_IMAGE_MAGIC_OFFSET + len(ARM64_IMAGE_MAGIC)
    return len(data) >= magic_end and (
        data[ARM64_IMAGE_MAGIC_OFFSET:magic_end] == ARM64_IMAGE_MAGIC
    )


def _pe_section(data: bytes, name: bytes) -> bytes | None:
    # Minimal PE/COFF section-table reader:
    #   0x00: MS-DOS header, starts with "MZ"
    #   0x3c: little-endian offset of the PE signature
    #   PE header:
    #     +0:  "PE\0\0" signature
    #     +6:  section count
    #     +20: optional header size
    #   Section table:
    #     one 40-byte header per section
    #     +0:  8-byte NUL-padded section name
    #     +16: raw section size
    #     +20: raw section file offset

    pe_offset = _pe_header_offset(data)
    if pe_offset is None:
        return None

    section_count = _u16(data, pe_offset + SECTION_COUNT_OFFSET)
    optional_header_size = _u16(data, pe_offset + OPTIONAL_HEADER_SIZE_OFFSET)
    if section_count is None or optional_header_size is None:
        return None

    section_offset = pe_offset + PE_SIGNATURE_SIZE + COFF_HEADER_SIZE
    section_offset += optional_header_size
    for index in range(section_count):
        offset = section_offset + index * SECTION_HEADER_SIZE
        if offset + SECTION_HEADER_SIZE > len(data):
            return None

        section_name = data[offset : offset + SECTION_NAME_SIZE].rstrip(b"\0")
        if section_name != name:
            continue

        raw_size = _u32(data, offset + SECTION_RAW_SIZE_OFFSET)
        raw_offset = _u32(data, offset + SECTION_RAW_OFFSET_OFFSET)
        if raw_size is None or raw_offset is None:
            return None
        if raw_size == 0 or raw_offset + raw_size > len(data):
            return None
        return data[raw_offset : raw_offset + raw_size]

    return None


def _parse_zboot(data: bytes) -> tuple[str, bytes] | None:
    # Linux EFI zboot header:
    #   +0:  MS-DOS magic, "MZ"
    #   +4:  image type, "zimg"
    #   +8:  little-endian payload offset
    #   +12: little-endian payload size
    #   +24: NUL-terminated compression type, up to 32 bytes
    #   +56: Linux PE magic
    if (
        len(data) < ZBOOT_HEADER_SIZE
        or data[0:2] != PE_MSDOS_MAGIC
        or data[4:8] != ZBOOT_MAGIC
        or data[ZBOOT_LINUX_MAGIC] != EFI_PE_LINUX_MAGIC
    ):
        return None

    payload_offset = _u32(data, ZBOOT_PAYLOAD_OFFSET)
    payload_size = _u32(data, ZBOOT_PAYLOAD_SIZE)
    if payload_offset is None or payload_size is None:
        return None
    if payload_size == 0 or payload_offset + payload_size > len(data):
        raise KernelImageError("invalid arm64 EFI zboot payload range")

    compression = data[ZBOOT_COMPRESSION_TYPE].split(b"\0", 1)[0]
    compression = compression.decode("ascii", errors="replace")
    payload = data[payload_offset : payload_offset + payload_size]
    return compression, payload


def _decompress_zstd(payload: bytes, image: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        # zstd can write directly to the same-directory temporary file used for
        # atomic publication. _write_atomic() takes bytes, which would require
        # buffering the complete decompressed image in Python first.
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            proc = subprocess.run(
                ["zstd", "-q", "-d", "-c"],
                input=payload,
                stdout=tmp,
                stderr=subprocess.PIPE,
                check=False,
                # Set the output-file limit in the child before executing zstd,
                # without changing the limits of the virtme-ng process.
                preexec_fn=_limit_decompressed_output,
            )
    except FileNotFoundError as exc:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise KernelImageError(
            f"arm64 EFI zboot image {image} uses zstd compression, "
            "but zstd is not installed"
        ) from exc
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise

    assert tmp_path is not None
    # Exceeding RLIMIT_FSIZE makes the kernel terminate zstd with SIGXFSZ.
    # Python reports signal termination as the negative signal number.
    if proc.returncode == -signal.SIGXFSZ:
        tmp_path.unlink(missing_ok=True)
        raise _decompressed_image_too_large(image)
    if proc.returncode != 0:
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        tmp_path.unlink(missing_ok=True)
        raise KernelImageError(
            f"failed to decompress arm64 EFI zboot image {image}: {error}"
        )
    _publish_atomic(output, tmp_path)


def _limit_decompressed_output() -> None:
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_DECOMPRESSED_SIZE, MAX_DECOMPRESSED_SIZE),
    )


def _decompressed_image_too_large(image: Path) -> KernelImageError:
    limit_mib = MAX_DECOMPRESSED_SIZE // (1024 * 1024)
    return KernelImageError(
        f"decompressed arm64 kernel image {image} exceeds the {limit_mib} MiB limit"
    )


def _cached_image_path(cache_dir: Path, image: Path) -> Path:
    digest = hashlib.sha256()
    try:
        with image.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise KernelImageError(f"failed to read kernel image {image}: {exc}") from exc
    return _cached_image_path_from_digest(cache_dir, digest.hexdigest())


def _cached_image_path_from_digest(cache_dir: Path, digest: str) -> Path:
    return Path(cache_dir, "kernel-images", "arm64", digest, "Image")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The cache path is content-addressed, so parallel virtme-ng instances may
    # normalize the same image. Write a complete temporary file first, then
    # publish it with an atomic rename inside the same directory.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    _publish_atomic(path, tmp_path)


def _publish_atomic(path: Path, tmp_path: Path) -> None:
    try:
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _u16(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int | None:
    if offset + 4 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 4], "little")
