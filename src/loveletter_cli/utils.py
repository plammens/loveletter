import ipaddress
import socket
import sys
from functools import lru_cache

import more_itertools as mitt
import netifaces


@lru_cache
def get_public_ip() -> ipaddress.IPv4Address:
    import urllib.request, urllib.error

    try:
        ip = urllib.request.urlopen("http://ident.me").read().decode()
    except urllib.error.URLError:
        raise RuntimeError("Couldn't get public IP") from None

    return ipaddress.ip_address(ip)


def get_local_ip() -> ipaddress.IPv4Address:
    return ipaddress.ip_address(_get_local_ip())


def _get_local_ip() -> str:
    try:
        default_gateway_ip = netifaces.gateways()["default"][netifaces.AF_INET][0]
    except KeyError:
        return "127.0.0.1"

    # get the IP by simulating connecting to the default gateway
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect((default_gateway_ip, 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


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
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
