# -*- mode: python -*-
# cpiowriter: A barebones initramfs writer
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643


class FileMetaData:
    def __init__(self, **kwargs):
        # Define default values for the metadata
        defaults = {
            "ino": None,
            "nlink": None,
            "uid": 0,
            "gid": 0,
            "mtime": 0,
            "devmajor": 0,
            "devminor": 0,
            "rdevmajor": 0,
            "rdevminor": 0,
        }

        # Update defaults with any provided keyword arguments
        self.meta_data = {**defaults, **kwargs}

    def get(self, key):
        return self.meta_data.get(key)

    def set(self, key, value):
        self.meta_data[key] = value


class CpioWriter:
    TYPE_DIR = 0o0040000
    TYPE_REG = 0o0100000
    TYPE_SYMLINK = 0o0120000
    TYPE_CHRDEV = 0o0020000
    TYPE_MASK = 0o0170000

    def __init__(self, f):
        self.__f = f
        self.__totalsize = 0
        self.__next_ino = 0

    def __write(self, data):
        self.__f.write(data)
        self.__totalsize += len(data)

    def write_object(self, name, body, mode, meta_data=None):
        # Set default metadata if not provided
        meta_data = meta_data or FileMetaData()

        # Ensure nlink is set correctly based on mode
        if meta_data.get("nlink") is None:
            meta_data.set(
                "nlink",
                2 if (mode & CpioWriter.TYPE_MASK) == CpioWriter.TYPE_DIR else 1,
            )

        if b"\0" in name:
            raise ValueError("Filename cannot contain a NUL")

        namesize = len(name) + 1

        if isinstance(body, bytes):
            filesize = len(body)
        else:
            filesize = body.seek(0, 2)
            body.seek(0)

        # Set default ino if not provided
        if meta_data.get("ino") is None:
            meta_data.set("ino", self.__next_ino)
            self.__next_ino += 1

        # Prepare fields list using metadata
        fields = [
            meta_data.get("ino"),
            mode,
            meta_data.get("uid"),
            meta_data.get("gid"),
            meta_data.get("nlink"),
            meta_data.get("mtime"),
            filesize,
            meta_data.get("devmajor"),
            meta_data.get("devminor"),
            meta_data.get("rdevmajor"),
            meta_data.get("rdevminor"),
            namesize,
            0,
        ]

        hdr = ("070701" + "".join(f"{f:08X}" for f in fields)).encode("ascii")

        self.__write(hdr)
        self.__write(name)
        self.__write(b"\0")
        self.__write(((2 - namesize) % 4) * b"\0")

        if isinstance(body, bytes):
            self.__write(body)
        else:
            while True:
                buf = body.read(65536)
                if buf == b"":
                    break
                self.__write(buf)

        self.__write(((-filesize) % 4) * b"\0")

    def write_trailer(self):
        self.write_object(
            name=b"TRAILER!!!", body=b"", mode=0, meta_data=FileMetaData(ino=0, nlink=1)
        )
        self.__write(((-self.__totalsize) % 512) * b"\0")

    def mkdir(self, name, mode):
        self.write_object(name=name, body=b"", mode=CpioWriter.TYPE_DIR | mode)

    def symlink(self, src, dst):
        self.write_object(name=dst, body=src, mode=CpioWriter.TYPE_SYMLINK | 0o777)

    def write_file(self, name, body, mode):
        self.write_object(name=name, body=body, mode=CpioWriter.TYPE_REG | mode)

    def mkchardev(self, name, dev, mode):
        major, minor = dev
        self.write_object(
            name=name,
            body=b"",
            mode=CpioWriter.TYPE_CHRDEV | mode,
            meta_data=FileMetaData(
                rdevmajor=major,
                rdevminor=minor,
            ),
        )
