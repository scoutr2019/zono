"""Send a stream to a smart TV on the local network (UPnP / DLNA MediaRenderer).

Most Samsung, LG, Sony, Philips and Android TVs accept this: the TV fetches the stream itself from the provider.
"""
import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

urlopen = build_opener(ProxyHandler({})).open  # TVs are on the home network: never go through a proxy
from xml.sax.saxutils import escape

AV = "urn:schemas-upnp-org:service:AVTransport:1"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _describe(location):
    with urlopen(Request(location, headers={"User-Agent": "Zono"}), timeout=3) as response:
        tree = ET.fromstring(response.read(512 * 1024))
    base = next((e.text for e in tree.iter() if _local(e.tag) == "URLBase" and e.text), location)
    name, model, control = "", "", None
    for element in tree.iter():
        tag = _local(element.tag)
        if tag == "friendlyName" and not name:
            name = (element.text or "").strip()
        elif tag == "modelName" and not model:
            model = (element.text or "").strip()
        elif tag == "service":
            fields = {_local(child.tag): (child.text or "").strip() for child in element}
            if "AVTransport" in fields.get("serviceType", "") and fields.get("controlURL"):
                control = urljoin(base, fields["controlURL"])
    if not control:
        return None
    return {"name": name or urlsplit(location).hostname, "model": model, "control": control, "location": location}


def _search(target, st):
    return (f"M-SEARCH * HTTP/1.1\r\nHOST: {target}\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: {st}\r\n"
            "USER-AGENT: Windows/10 UPnP/1.1 Zono/1.0\r\n\r\n").encode()


TARGETS = ("urn:schemas-upnp-org:device:MediaRenderer:1", "urn:schemas-upnp-org:service:AVTransport:1", "ssdp:all")


def local_addresses():
    """IPv4 addresses of this PC on home networks (a PC often has extra adapters for VPN, Hyper-V or WSL)."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        found.insert(0, probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    result = []
    for address in found:
        if address.startswith(("127.", "169.254.", "0.")) or address in result:
            continue
        result.append(address)
    return result


def _private(address):
    a, b = (int(x) for x in address.split(".")[:2])
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def discover(timeout=4.0):
    """Return the TVs that answer within `timeout` seconds.

    Searches on every network adapter, and also asks every address of the home network directly: Windows
    Firewall often drops the TV's answer to a multicast search, but lets through answers to a direct question."""
    sockets = []
    for address in local_addresses() or ["0.0.0.0"]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.bind((address, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if address != "0.0.0.0":
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
            sock.setblocking(False)
            sockets.append((address, sock))
        except OSError:
            continue
    locations = []
    try:
        for round_ in range(2):
            for address, sock in sockets:
                for st in TARGETS:
                    try:
                        sock.sendto(_search("239.255.255.250:1900", st), ("239.255.255.250", 1900))
                    except OSError:
                        pass
                if round_ == 0 and address != "0.0.0.0" and _private(address):
                    prefix = address.rsplit(".", 1)[0]
                    packet = _search("239.255.255.250:1900", TARGETS[0])
                    for host in range(1, 255):
                        target = f"{prefix}.{host}"
                        if target != address:
                            try:
                                sock.sendto(packet, (target, 1900))
                            except OSError:
                                pass
            time.sleep(0.15)
        import select
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([sock for _, sock in sockets], [], [], 0.3)
            for sock in ready:
                try:
                    packet, _ = sock.recvfrom(65507)
                except OSError:
                    continue
                for line in packet.decode("utf-8", "replace").split("\r\n"):
                    if line.lower().startswith("location:"):
                        location = line.split(":", 1)[1].strip()
                        if location and location not in locations:
                            locations.append(location)
    finally:
        for _, sock in sockets:
            sock.close()
    devices = []
    from concurrent.futures import ThreadPoolExecutor

    def describe(location):
        try:
            return _describe(location)
        except (OSError, ET.ParseError, ValueError):
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        for device in pool.map(describe, locations[:60]):
            if device and all(d["control"] != device["control"] for d in devices):
                devices.append(device)
    return devices


def envelope(action, arguments):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{AV}">{arguments}</u:{action}></s:Body></s:Envelope>')


def _soap(device, action, arguments="<InstanceID>0</InstanceID>"):
    request = Request(device["control"], data=envelope(action, arguments).encode("utf-8"), method="POST",
                      headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{AV}#{action}"',
                               "User-Agent": "Zono"})
    with urlopen(request, timeout=6) as response:
        return response.read()


def cast_url(url):
    """TVs handle MPEG-TS far better than HLS playlists, and Xtream serves both for live channels."""
    if "/live/" in url and url.endswith(".m3u8"):
        return url[:-5] + ".ts"
    return url


def mime_of(url):
    path = urlsplit(url).path.lower()
    for ending, kind in ((".ts", "video/mp2t"), (".mp4", "video/mp4"), (".m4v", "video/mp4"), (".mkv", "video/x-matroska"),
                         (".avi", "video/x-msvideo"), (".m3u8", "application/vnd.apple.mpegurl"), (".mov", "video/quicktime")):
        if path.endswith(ending):
            return kind
    return "video/mp4"


def metadata(title, url, kind):
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="0" parentID="-1" restricted="1">'
            f'<dc:title>{escape(title)}</dc:title><upnp:class>object.item.videoItem</upnp:class>'
            f'<res protocolInfo="http-get:*:{kind}:*">{escape(url)}</res></item></DIDL-Lite>')


def play(device, url, title):
    url = cast_url(url)
    kind = mime_of(url)
    try:
        _soap(device, "Stop")
    except OSError:
        pass
    arguments = (f"<InstanceID>0</InstanceID><CurrentURI>{escape(url)}</CurrentURI>"
                 f"<CurrentURIMetaData>{escape(metadata(title, url, kind))}</CurrentURIMetaData>")
    _soap(device, "SetAVTransportURI", arguments)
    _soap(device, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")


def stop(device):
    _soap(device, "Stop")


def pause(device):
    _soap(device, "Pause")


def resume(device):
    _soap(device, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")
