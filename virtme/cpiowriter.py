# -*- mode: python -*-
# cpiowriter: A barebones initramfs writer
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643


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

    def write_object(
        self,
        name,
        body,
        mode,
        ino=None,
        nlink=None,
        uid=0,
        gid=0,
        mtime=0,
        devmajor=0,
        devminor=0,
        rdevmajor=0,
        rdevminor=0,
    ):
        if nlink is None:
            nlink = 2 if (mode & CpioWriter.TYPE_MASK) == CpioWriter.TYPE_DIR else 1

        if b"\0" in name:
            raise ValueError("Filename cannot contain a NUL")

        namesize = len(name) + 1

        if isinstance(body, bytes):
            filesize = len(body)
        else:
            filesize = body.seek(0, 2)
            body.seek(0)

        if ino is None:
            ino = self.__next_ino
            self.__next_ino += 1

        fields = [
            ino,
            mode,
            uid,
            gid,
            nlink,
            mtime,
            filesize,
            devmajor,
            devminor,
            rdevmajor,
            rdevminor,
            namesize,
            0,
        ]
        hdr = ("070701" + "".join("%08X" % f for f in fields)).encode("ascii")

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
        self.write_object(name=b"TRAILER!!!", body=b"", mode=0, ino=0, nlink=1)
        self.__write(((-self.__totalsize) % 512) * b"\0")

    def mkdir(self, name, mode):
        self.write_object(name=name, mode=CpioWriter.TYPE_DIR | mode, body=b"")

    def symlink(self, src, dst):
        self.write_object(name=dst, mode=CpioWriter.TYPE_SYMLINK | 0o777, body=src)

    def write_file(self, name, body, mode):
        self.write_object(name=name, body=body, mode=CpioWriter.TYPE_REG | mode)

    def mkchardev(self, name, dev, mode):
        major, minor = dev
        self.write_object(
            name=name,
            mode=CpioWriter.TYPE_CHRDEV | mode,
            rdevmajor=major,
            rdevminor=minor,
            body=b"",
        )
