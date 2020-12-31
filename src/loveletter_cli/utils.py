import ipaddress
import shutil
import socket
from functools import lru_cache

import valid8


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


@valid8.validate_arg("filler", valid8.validation_lib.length_between(1, 1))
def print_header(text: str, filler: str = "-"):
    width, _ = shutil.get_terminal_size()
    print(format(f" {text} ", f"{filler}^{width - 1}"), end="\n\n")
