"""Bounded, process-local throttling for rejected authentication attempts."""
from collections import OrderedDict
import ipaddress
import math
import threading
import time


def client_ip(peer, forwarded=''):
    """Only the loopback reverse proxy may supply XFF; use its rightmost hop.

    Caddy must overwrite/append the actual peer and must not blindly trust
    arbitrary forwarded headers. Direct remote peers never get to choose a key.
    """
    def canonical(value):
        address = ipaddress.ip_address(value.strip())
        return str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)
    try:
        actual = canonical(peer)
        if ipaddress.ip_address(actual).is_loopback and forwarded:
            return canonical(forwarded.rsplit(',', 1)[-1])
        return actual
    except ValueError:
        return str(peer)


class FailedAuthLimiter:
    def __init__(self, threshold=8, window=300, cooldown=600, capacity=4096, clock=time.monotonic):
        self.threshold, self.window, self.cooldown = threshold, window, cooldown
        self.capacity, self.clock = capacity, clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def _entry(self, key, now):
        value = self.entries.get(key)
        if value and ((value['until'] and now >= value['until']) or
                      (not value['until'] and now-value['first'] >= self.window)):
            self.entries.pop(key, None)
            return None
        return value

    def remaining(self, key):
        with self.lock:
            now = self.clock()
            value = self._entry(key, now)
            return max(0, math.ceil(value['until']-now)) if value else 0

    def failure(self, key):
        with self.lock:
            now = self.clock()
            value = self._entry(key, now)
            if value and value['until'] > now:
                return math.ceil(value['until']-now)  # Rejected traffic cannot extend the ban.
            if value is None:
                value = {'first': now, 'count': 0, 'until': 0}
            value['count'] += 1
            if value['count'] >= self.threshold:
                value['until'] = now+self.cooldown
            self.entries[key] = value
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
            return max(0, math.ceil(value['until']-now))

    def success(self, key):
        with self.lock:
            self.entries.pop(key, None)
