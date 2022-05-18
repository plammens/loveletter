import ipaddress
import socket
import sys
from functools import lru_cache

import more_itertools as mitt


@lru_cache
def get_public_ip() -> ipaddress.IPv4Address:
    import urllib.request, urllib.error

    try:
        ip = urllib.request.urlopen("http://ident.me").read().decode()
    except urllib.error.URLError:
        raise RuntimeError("Couldn't get public IP") from None

    return ipaddress.ip_address(ip)


def get_local_ip() -> ipaddress.IPv4Address:
    return ipaddress.ip_address(socket.gethostbyname(socket.getfqdn()))


def is_valid_ipv4(ip: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, ip)
    except OSError:
        return False
    else:
        return True


def camel_to_phrase(name: str) -> str:
    """Convert camel/Pascal-case into a phrase with space-separated lowercase words."""
    return " ".join("".join(w).lower() for w in mitt.split_before(name, str.isupper))


def running_as_pyinstaller_executable() -> bool:
    """Determine whether the interpreter is running within a PyInstaller executable."""
    return getattr(sys, "frozen", False)
