"""Execute a command with network-related syscalls denied via libseccomp."""
import ctypes
import errno
import os
import sys

SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000


def deny_network() -> None:
    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]

    ctx = lib.seccomp_init(SCMP_ACT_ALLOW)
    if not ctx:
        raise RuntimeError("seccomp_init failed")
    try:
        action = SCMP_ACT_ERRNO | errno.EPERM
        for name in (
            b"socket", b"socketpair", b"connect", b"bind", b"listen",
            b"accept", b"accept4", b"sendto", b"recvfrom", b"sendmsg", b"recvmsg",
        ):
            num = lib.seccomp_syscall_resolve_name(name)
            if num >= 0 and lib.seccomp_rule_add(ctx, action, num, 0) != 0:
                raise RuntimeError(f"seccomp rule failed: {name.decode()}")
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError("seccomp_load failed")
    finally:
        lib.seccomp_release(ctx)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: terminal_sandbox.py COMMAND [ARGS...]")
    deny_network()
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
