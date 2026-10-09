"""Process-wide socket guard. Install before startup; only loopback is permitted.
This guards Python sockets (including transitive dependencies), not unrelated OS processes.
"""
import ipaddress
import sys

installed = False
blocked_connections = 0


def audit(event: str, args: tuple):
    global blocked_connections
    if event in ('socket.connect', 'socket.sendto'):
        address = args[-1]
        if isinstance(address, tuple):
            host = address[0]
        else:
            return  # local Unix-domain sockets
    elif event == 'socket.getaddrinfo':
        host = args[0]
        if host is None:
            return
    else:
        return
    if isinstance(host, bytes):
        host = host.decode('ascii', errors='replace')
    try:
        allowed = host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        blocked_connections += 1
        raise PermissionError('WardNote permits loopback network connections only.')


def install_guard():
    global installed
    if not installed:
        sys.addaudithook(audit)
        installed = True
