"""Ask a TURN server for a relay allocation, using long-term credentials.

Proves the difference between "a TURN URL is configured" and "a relay will
actually accept us" - which is the difference between fixing the no-TURN bug
and only appearing to. Run this against a new TURN account *before* putting
it in Render's environment.

    python tools/turn_probe.py <host> <port> <username> <credential>

Exits 0 on a successful allocation. RFC 5766 Allocate over TCP, stdlib only,
no dependencies.

Reading the result:

  ALLOCATED       the relay works and these credentials are accepted.
  401 on the 2nd  credentials rejected - the server checked and said no.
  400 on the 2nd  the server refused the request without evaluating the
                  credentials. Open Relay's public endpoint does this for
                  every input, which is how its uselessness was established:
                  the documented credentials, a wrong password and a
                  nonexistent user all return 400.

A 401 on the *first* exchange is normal and expected - it is the long-term
credential challenge that carries the realm and nonce.
"""
import hashlib
import hmac
import os
import socket
import struct
import sys

MAGIC = 0x2112A442
ALLOCATE_REQUEST = 0x0003
ALLOCATE_SUCCESS = 0x0103
ALLOCATE_ERROR = 0x0113

ATTR_USERNAME = 0x0006
ATTR_MESSAGE_INTEGRITY = 0x0008
ATTR_ERROR_CODE = 0x0009
ATTR_REALM = 0x0014
ATTR_NONCE = 0x0015
ATTR_XOR_RELAYED_ADDRESS = 0x0016
ATTR_REQUESTED_TRANSPORT = 0x0019
ATTR_LIFETIME = 0x000D


def pad(b):
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def attr(t, v):
    return struct.pack("!HH", t, len(v)) + pad(v)


def message(msg_type, txid, attrs, integrity_key=None):
    body = b"".join(attrs)
    if integrity_key is None:
        return struct.pack("!HHI", msg_type, len(body), MAGIC) + txid + body
    # The length used for the HMAC must already account for the 24-byte
    # MESSAGE-INTEGRITY attribute that is about to be appended.
    header = struct.pack("!HHI", msg_type, len(body) + 24, MAGIC) + txid
    digest = hmac.new(integrity_key, header + body, hashlib.sha1).digest()
    return header + body + attr(ATTR_MESSAGE_INTEGRITY, digest)


def parse(data):
    msg_type, length = struct.unpack("!HH", data[:4])
    out, i, end = {}, 20, 20 + length
    while i + 4 <= end:
        t, l = struct.unpack("!HH", data[i:i + 4])
        out[t] = data[i + 4:i + 4 + l]
        i += 4 + l + ((4 - l % 4) % 4)
    return msg_type, out


def xor_addr(v):
    family = v[1]
    port = struct.unpack("!H", v[2:4])[0] ^ (MAGIC >> 16)
    if family == 0x01:
        raw = bytes(a ^ b for a, b in zip(v[4:8], struct.pack("!I", MAGIC)))
        return f"{socket.inet_ntoa(raw)}:{port}"
    return f"[ipv6]:{port}"


def probe(host, port, user, password, timeout=15):
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        txid = os.urandom(12)
        base = [attr(ATTR_REQUESTED_TRANSPORT, struct.pack("!BBBB", 17, 0, 0, 0))]

        sock.sendall(message(ALLOCATE_REQUEST, txid, base))
        msg_type, attrs = parse(sock.recv(4096))
        if msg_type != ALLOCATE_ERROR:
            return False, f"expected a 401 challenge first, got {msg_type:#06x}"

        code = attrs.get(ATTR_ERROR_CODE, b"\x00\x00\x04\x01")
        challenge = code[2] * 100 + code[3]
        realm = attrs.get(ATTR_REALM, b"")
        nonce = attrs.get(ATTR_NONCE, b"")
        print(f"  challenge   : {challenge} realm={realm.decode(errors='replace')!r}")
        if challenge != 401 or not realm or not nonce:
            return False, f"unusable challenge ({challenge})"

        key = hashlib.md5(
            f"{user}:{realm.decode()}:{password}".encode()
        ).digest()
        txid = os.urandom(12)
        authed = base + [
            attr(ATTR_USERNAME, user.encode()),
            attr(ATTR_REALM, realm),
            attr(ATTR_NONCE, nonce),
        ]
        sock.sendall(message(ALLOCATE_REQUEST, txid, authed, integrity_key=key))
        msg_type, attrs = parse(sock.recv(4096))

        if msg_type == ALLOCATE_SUCCESS:
            relayed = attrs.get(ATTR_XOR_RELAYED_ADDRESS)
            lifetime = struct.unpack("!I", attrs[ATTR_LIFETIME])[0] if ATTR_LIFETIME in attrs else "?"
            return True, f"relay {xor_addr(relayed) if relayed else '?'} lifetime {lifetime}s"

        code = attrs.get(ATTR_ERROR_CODE, b"\x00\x00\x00\x00")
        return False, f"allocate refused: {code[2] * 100 + code[3]} {code[4:].decode(errors='replace')}"
    finally:
        sock.close()


if __name__ == "__main__":
    host, port, user, pw = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    print(f"TURN {host}:{port} as {user!r}")
    try:
        ok, detail = probe(host, port, user, pw)
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    print(f"  {'ALLOCATED   ' if ok else 'FAILED      '}: {detail}")
    sys.exit(0 if ok else 1)
