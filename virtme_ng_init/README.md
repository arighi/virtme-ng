# virtme-ng-init: fast init process for virtme-ng

virtme-ng-init is an extremely lightweight init process for virtme-ng [1]
implemented in Rust.

Its primary goal is to speed up the boot time of virtme-ng instances.

virtme-ng-init is able to perform any necessary initialization in the
virtualized environment, such as mounting filesystems, starting essential
services, and configuring the system before handing over control to the main
user-space processes (typicall a shell session).

[1] https://github.com/arighi/virtme-ng

# Result

 - virtme-init (bash implementation):
```
$ time virtme-ng --exec 'uname -r'
6.4.0-rc3-virtme

real	0m1.146s
user	0m0.829s
sys	0m1.048s

$ time virtme-ng --net user --exec 'ip addr show dev eth0'
2: eth0: <NO-CARRIER,BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state DOWN group default qlen 1000
    link/ether 52:54:00:12:34:56 brd ff:ff:ff:ff:ff:ff
    inet 10.0.2.15/24 scope global eth0
       valid_lft forever preferred_lft forever

real	0m1.282s
user	0m0.930s
sys	0m1.219s
```

 - virtme-ng-init (Rust implementation):
```
$ time virtme-ng --exec 'uname -r'
6.4.0-rc3-virtme

real	0m0.906s
user	0m0.654s
sys	0m0.684s

$ time virtme-ng --net user --exec 'ip addr show dev eth0'
2: eth0: <NO-CARRIER,BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state DOWN group default qlen 1000
    link/ether 52:54:00:12:34:56 brd ff:ff:ff:ff:ff:ff
    inet 10.0.2.15/24 scope global eth0
       valid_lft forever preferred_lft forever

real	0m0.972s
user	0m0.736s
sys	0m0.795s
```

# Building

Static building is necessary as this binary is going to be executed
before the file system is up and running.

```
RUSTFLAGS='-C target-feature=+crt-static' cargo build -r
```

# Local installation

Put the binary into virtme/guest/bin/.
e.g. when used as a submodule:
```
cp target/release/virtme-ng-init ../virtme/guest/bin
```

# Credits

Author: Andrea Righi <andrea.righi@canonical.com>
