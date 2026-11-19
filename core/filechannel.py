"""The file channel (fork: Scotty, FILES.md, WIRE.md section 11): files and folders copied on one
machine, fetched by the other over their own TCP connection so the input link never carries their
bytes and the pointer never waits behind them.

The sender offers paths with `FileServer.offer`, which lists them and returns the `files`
manifest's fields; the manifest itself rides the encrypted input link. The receiver calls `fetch`
with that manifest. Pull model: the receiver asks for each file in turn, owns every write, and
cancels by closing the connection.

The connection, receiver first:

    receiver -> sender   b"SCOTTY1", the 16-byte transfer id, 32 random bytes
    sender   -> receiver b"SCOTTY1", 32 random bytes

Then every frame each way is a 4-byte big-endian length and a NaCl SecretBox (XSalsa20-Poly1305)
of one kind byte and its body. Each direction has its own key, HKDF-SHA256 over the ticket with
both random values as salt and the transfer id and direction as info, so the ticket never crosses
this connection and no key is ever used on two connections. Nonces are a per-direction counter
from 1, so a frame that is replayed, dropped or reordered fails to open and ends the connection.

Kind 1 is a JSON object (`op`), kind 2 is file bytes, at most CHUNK_BYTES a frame:

    receiver: {"op": "list"}
    sender:   {"op": "entries", "entries": [{"path", "size"} or {"path", "dir": true}, ...]}  repeated
              {"op": "end", "count", "total_bytes"}
    receiver: {"op": "get", "index"}
    sender:   kind-2 frames carrying exactly that entry's size, then {"op": "done", "sha256"}
              (or {"op": "error", "why"} instead, at any point)
    receiver: {"op": "bye"}

The sender hashes what it sent and the receiver what it wrote; a mismatch fails the transfer.
Files land in a staging folder under the drop folder and move into place, under a dated folder,
only when everything arrived and checked out; a cancelled or failed transfer leaves nothing.
"""

import datetime
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import struct
import threading
import time

from nacl.bindings import crypto_secretbox, crypto_secretbox_open
from nacl.exceptions import CryptoError

from core import protocol

LOGGER = logging.getLogger(__name__)

MAGIC = b"SCOTTY1"
RANDOM_SIZE = 32
CHUNK_BYTES = 1024 * 1024
FRAME_OVERHEAD = 16 + 1
MAX_FRAME_BYTES = CHUNK_BYTES + FRAME_OVERHEAD
CONTROL_MAX_BYTES = 1024 * 1024
ENTRIES_PER_FRAME = 2000
OFFER_SECONDS = 10 * 60
MAX_OFFERS = 4
SOCKET_SECONDS = 30.0
HANDSHAKE_SECONDS = 10.0
KIND_CONTROL = 1
KIND_DATA = 2
SALT = b"scotty-files-v1"
TO_SENDER = b"to-sender"
TO_RECEIVER = b"to-receiver"
STAGING = ".scotty-incoming"
DISK_HEADROOM_BYTES = 512 * 1024 * 1024  # never fill the drive: Windows needs room to run
PROGRESS_SECONDS = 0.25
MAX_CONNECTIONS = 8
PER_ADDRESS = 2


class TransferError(Exception):
    """The transfer could not finish; `str()` is a sentence for the person."""


class TransferCancelled(TransferError):
    pass


def _key(ticket: bytes, transfer: bytes, random_r: bytes, random_s: bytes, direction: bytes) -> bytes:
    return protocol.hkdf_sha256(ticket, SALT + random_r + random_s, transfer + direction)


class _Channel:
    """One connection's framing and cipher state, for one end."""

    def __init__(self, sock, send_key, recv_key):
        self.sock = sock
        self._send_key = send_key
        self._recv_key = recv_key
        self._sent = 0
        self._received = 0

    @staticmethod
    def _nonce(counter):
        return bytes(16) + counter.to_bytes(8, "big")

    def send(self, kind, body: bytes):
        self._sent += 1
        sealed = crypto_secretbox(bytes([kind]) + body, self._nonce(self._sent), self._send_key)
        self.sock.sendall(struct.pack(">I", len(sealed)) + sealed)

    def send_control(self, message: dict):
        self.send(KIND_CONTROL, json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def recv(self, deadline=None):
        length = struct.unpack(">I", _recv_exact(self.sock, 4, deadline))[0]
        if not FRAME_OVERHEAD <= length <= MAX_FRAME_BYTES:
            raise TransferError("the other machine sent a frame of an impossible size")
        sealed = _recv_exact(self.sock, length, deadline)
        self._received += 1
        try:
            plain = crypto_secretbox_open(sealed, self._nonce(self._received), self._recv_key)
        except CryptoError as exc:
            raise TransferError("the file connection could not be authenticated") from exc
        kind, body = plain[0], plain[1:]
        if kind == KIND_CONTROL:
            if len(body) > CONTROL_MAX_BYTES:
                raise TransferError("the other machine sent too large a message")
            try:
                message = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise TransferError("the other machine sent a malformed message") from exc
            if not isinstance(message, dict) or not isinstance(message.get("op"), str):
                raise TransferError("the other machine sent a malformed message")
            return KIND_CONTROL, message
        if kind == KIND_DATA:
            return KIND_DATA, body
        raise TransferError("the other machine sent a frame of an unknown kind")


def _recv_exact(sock, count, deadline=None):
    """`count` bytes. With a `deadline` (time.monotonic) the whole read must finish by then, so a
    peer that trickles one byte at a time cannot hold the connection open."""
    data = bytearray()
    while len(data) < count:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TransferError("the other machine was too slow to start")
            sock.settimeout(left)
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise TransferError("the other machine closed the file connection")
        data.extend(chunk)
    return bytes(data)


# Listing what was copied

class _Entry:
    __slots__ = ("path", "size", "is_dir", "source", "mtime_ns")

    def __init__(self, path, size, is_dir, source, mtime_ns=None):
        self.path, self.size, self.is_dir, self.source, self.mtime_ns = path, size, is_dir, source, mtime_ns

    def wire(self):
        return {"path": self.path, "dir": True} if self.is_dir else {"path": self.path, "size": self.size}


def list_paths(paths, max_count=protocol.FILES_MAX_COUNT):
    """The entries under `paths` (absolute files and folders), relative to each path's parent, with
    "/" between components: folders first then their contents, sorted, symbolic links and junctions
    skipped so a loop cannot run forever. Raises TransferError for a name another machine could
    not create, two top-level items with the same name, or more than `max_count` files."""
    entries, names, count = [], [], 0
    for path in paths:
        path = os.path.abspath(path)
        name = os.path.basename(path.rstrip("\\/"))
        if not protocol.valid_file_name(name):
            raise TransferError(f"“{name}” cannot be sent: its name is not allowed on Windows")
        if name.casefold() in {existing.casefold() for existing in names}:
            raise TransferError(f"two copied items are both called “{name}”")
        names.append(name)
        if os.path.islink(path):
            continue
        if os.path.isdir(path):
            entries.append(_Entry(name, 0, True, path))
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)) and not _is_junction(os.path.join(root, d)))
                relative_root = os.path.relpath(root, os.path.dirname(path)).replace(os.sep, "/")
                for folder in dirs:
                    _check_name(folder, relative_root)
                    entries.append(_Entry(f"{relative_root}/{folder}", 0, True, os.path.join(root, folder)))
                for file_name in sorted(files):
                    source = os.path.join(root, file_name)
                    if os.path.islink(source):
                        continue
                    _check_name(file_name, relative_root)
                    count += 1
                    if count > max_count:
                        raise TransferError(f"more than {max_count:,} files were copied")
                    entries.append(_file_entry(f"{relative_root}/{file_name}", source))
        elif os.path.isfile(path):
            count += 1
            entries.append(_file_entry(name, path))
        else:
            raise TransferError(f"“{name}” is no longer there")
    if not names:
        raise TransferError("nothing that can be sent was copied")
    return names, entries


def _file_entry(path, source):
    stat = os.stat(source)
    return _Entry(path, stat.st_size, False, source, stat.st_mtime_ns)


def _check_name(name, where):
    if not protocol.valid_file_name(name):
        raise TransferError(f"“{where}/{name}” cannot be sent: its name is not allowed on Windows")


def _is_junction(path):
    """A junction or any other reparse point that is not a plain symbolic link: os.path.isjunction
    on Python 3.12 and later, the file's own reparse-point attribute before that."""
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None and is_junction(path):
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


# The sender

def _plain_address(address):
    """An IP as text without an IPv6 zone and with an IPv4-mapped IPv6 address as plain IPv4, so
    one machine always compares equal to itself however its connection arrived."""
    address = str(address).split("%", 1)[0]
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    mapped = getattr(parsed, "ipv4_mapped", None)
    return str(mapped or parsed)


def _addresses_of(host):
    """Every IP `host` (a name or an address) stands for, as _plain_address gives them; empty when
    it cannot be looked up."""
    try:
        return {_plain_address(info[4][0]) for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return set()


class Offer:
    def __init__(self, transfer, ticket, names, entries, allowed_host, made_at):
        self.transfer = transfer
        self.ticket = ticket
        self.names = names
        self.entries = entries
        self.allowed_host = allowed_host
        self.allowed_addresses = None  # the IPs allowed_host stands for, or None for any
        self.count = sum(1 for entry in entries if not entry.is_dir)
        self.total_bytes = sum(entry.size for entry in entries)
        self.made_at = made_at


class FileServer:
    """Serves offered files on `port` to the peer that holds an offer's ticket. Start it once;
    `offer` lists copied paths and returns the Offer whose fields make the `files` manifest."""

    def __init__(self, host="0.0.0.0", port=protocol.FILES_PORT, clock=time.monotonic):
        self._host, self._port = host, port
        self._clock = clock
        self._offers = {}
        self._lock = threading.Lock()
        self._sock = None
        self._closed = threading.Event()
        self._serving = {}  # connection: Offer, for cancel_sends
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._per_address = {}  # address: connections being served to it
        # on_progress(offer, state, sent_bytes): state is "sending" (sent_bytes so far), "sent" when
        # the receiver said bye with everything, or "stopped" when the connection ended before that.
        # Called on the serving thread.
        self.on_progress = None

    @property
    def port(self):
        return self._sock.getsockname()[1] if self._sock is not None else self._port

    def start(self):
        sock = None
        if self._host == "0.0.0.0" and socket.has_ipv6:
            # One dual-stack socket, so a peer reached over IPv6 can fetch too.
            try:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(("::", self._port))
            except OSError:
                if sock is not None:
                    sock.close()
                sock = None
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((self._host, self._port))
        sock.listen(MAX_CONNECTIONS)
        self._sock = sock
        threading.Thread(target=self._accept_loop, name="scotty-files-server", daemon=True).start()
        return self

    def close(self):
        self._closed.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def offer(self, paths, allowed_host=None) -> Offer:
        """List `paths` and keep them on offer for OFFER_SECONDS, to `allowed_host` only when given.
        Raises TransferError when they cannot be sent."""
        allowed = _addresses_of(allowed_host) if allowed_host is not None else None
        if allowed is not None and not allowed:
            raise TransferError(f"the other machine's address {allowed_host} could not be looked up")
        names, entries = list_paths(paths)
        offer = Offer(secrets.token_bytes(protocol.FILES_TRANSFER_SIZE), secrets.token_bytes(protocol.FILES_TICKET_SIZE),
                      names, entries, allowed_host, self._clock())
        offer.allowed_addresses = allowed
        with self._lock:
            self._expire_locked()
            # One live offer per peer: a newer copy withdraws what was copied before it, so an
            # older ticket opens nothing even if the peer kept it. A transfer already running
            # carries on; the receiver cancels it itself when the newer manifest arrives.
            for transfer in [t for t, old in self._offers.items() if old.allowed_host == allowed_host]:
                del self._offers[transfer]
            self._offers[offer.transfer] = offer
            while len(self._offers) > MAX_OFFERS:
                oldest = min(self._offers.values(), key=lambda item: item.made_at)
                del self._offers[oldest.transfer]
        return offer

    def manifest(self, offer: Offer) -> dict:
        return protocol.files_msg(offer.transfer, offer.ticket, self.port, offer.names, offer.count, offer.total_bytes)

    def cancel_sends(self) -> bool:
        """Stop every transfer being served now, and withdraw their offers. True when one was."""
        with self._lock:
            serving = list(self._serving.items())
            for _, offer in serving:
                self._offers.pop(offer.transfer, None)
        for conn, _ in serving:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return bool(serving)

    def has_offer(self, transfer) -> bool:
        with self._lock:
            self._expire_locked()
            return transfer in self._offers

    @property
    def sending(self) -> bool:
        with self._lock:
            return bool(self._serving)

    def _tell(self, offer, state, sent):
        callback = self.on_progress
        if callback is None:
            return
        try:
            callback(offer, state, sent)
        except Exception:
            LOGGER.exception("the sending progress could not be shown")

    def withdraw(self, transfer=None):
        with self._lock:
            if transfer is None:
                self._offers.clear()
            else:
                self._offers.pop(transfer, None)

    def _expire_locked(self):
        now = self._clock()
        for transfer in [t for t, offer in self._offers.items() if now - offer.made_at > OFFER_SECONDS]:
            del self._offers[transfer]

    def _accept_loop(self):
        while not self._closed.is_set():
            try:
                conn, address = self._sock.accept()
            except OSError:
                if self._closed.is_set():
                    return
                time.sleep(0.2)
                continue
            # A device on the network can open connections without a ticket. Only an address that
            # something is on offer to gets a thread at all, at most PER_ADDRESS of them and
            # MAX_CONNECTIONS in all, each with HANDSHAKE_SECONDS in total to authenticate.
            peer = _plain_address(address[0])
            with self._lock:
                self._expire_locked()
                wanted = any(offer.allowed_addresses is None or peer in offer.allowed_addresses
                             for offer in self._offers.values())
                crowded = self._per_address.get(peer, 0) >= PER_ADDRESS
                if wanted and not crowded and self._slots.acquire(blocking=False):
                    self._per_address[peer] = self._per_address.get(peer, 0) + 1
                else:
                    wanted = False
            if not wanted:
                LOGGER.info("refused a file connection from %s: nothing on offer to it, or too many", address[0])
                conn.close()
                continue
            threading.Thread(target=self._serve_slot, args=(conn, address, peer), name="scotty-files-serve",
                             daemon=True).start()

    def _serve_slot(self, conn, address, peer):
        try:
            self._serve(conn, address)
        finally:
            with self._lock:
                left = self._per_address.get(peer, 1) - 1
                if left:
                    self._per_address[peer] = left
                else:
                    self._per_address.pop(peer, None)
            self._slots.release()

    def _serve(self, conn, address):
        try:
            with conn:
                deadline = time.monotonic() + HANDSHAKE_SECONDS
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                head = _recv_exact(conn, len(MAGIC) + protocol.FILES_TRANSFER_SIZE + RANDOM_SIZE, deadline)
                if head[:len(MAGIC)] != MAGIC:
                    return
                transfer = head[len(MAGIC):len(MAGIC) + protocol.FILES_TRANSFER_SIZE]
                random_r = head[-RANDOM_SIZE:]
                with self._lock:
                    self._expire_locked()
                    offer = self._offers.get(transfer)
                if offer is None or (offer.allowed_addresses is not None and _plain_address(address[0]) not in offer.allowed_addresses):
                    LOGGER.info("refused a file connection from %s for an unknown or expired transfer", address[0])
                    return
                random_s = secrets.token_bytes(RANDOM_SIZE)
                conn.sendall(MAGIC + random_s)
                channel = _Channel(conn,
                                   _key(offer.ticket, transfer, random_r, random_s, TO_RECEIVER),
                                   _key(offer.ticket, transfer, random_r, random_s, TO_SENDER))
                with self._lock:
                    self._serving[conn] = offer
                progress = _Sent(self, offer)
                finished = False
                try:
                    finished = self._answer(channel, offer, progress, deadline)
                finally:
                    with self._lock:
                        self._serving.pop(conn, None)
                        if finished or progress.bytes >= offer.total_bytes:
                            # Single use: once every byte has gone out the ticket opens nothing,
                            # whether or not the receiver said bye.
                            self._offers.pop(offer.transfer, None)
                self._tell(offer, "sent" if finished else "stopped", progress.bytes)
        except (TransferError, OSError) as exc:
            LOGGER.info("file connection from %s ended: %s", address[0], exc)
            if "offer" in locals() and "progress" in locals():
                self._tell(offer, "stopped", progress.bytes)

    def _answer(self, channel, offer, progress, deadline):
        """True when the receiver said bye after taking everything it listed. Its first frame, the
        proof that it holds the ticket, must arrive by `deadline` like the greeting."""
        first = True
        while True:
            if first:
                kind, message = channel.recv(deadline)
                channel.sock.settimeout(SOCKET_SECONDS)
                first = False
            else:
                kind, message = channel.recv()
            if kind != KIND_CONTROL:
                raise TransferError("the receiver sent file bytes")
            op = message["op"]
            if op == "list":
                for start in range(0, len(offer.entries), ENTRIES_PER_FRAME):
                    channel.send_control({"op": "entries", "entries": [entry.wire() for entry in offer.entries[start:start + ENTRIES_PER_FRAME]]})
                channel.send_control({"op": "end", "count": offer.count, "total_bytes": offer.total_bytes})
            elif op == "get":
                index = message.get("index")
                if type(index) is not int or not 0 <= index < len(offer.entries) or offer.entries[index].is_dir:
                    raise TransferError("the receiver asked for something not on offer")
                self._send_file(channel, offer.entries[index], progress)
            elif op == "bye":
                return progress.bytes == offer.total_bytes
            else:
                raise TransferError(f"the receiver sent an unknown request {op!r}")

    def _send_file(self, channel, entry, progress):
        digest, left = hashlib.sha256(), entry.size
        try:
            source = open(entry.source, "rb")
        except OSError:
            channel.send_control({"op": "error", "why": f"“{entry.path}” could not be opened on the other machine"})
            return
        with source:
            stat = os.fstat(source.fileno())
            if stat.st_size != entry.size or (entry.mtime_ns is not None and stat.st_mtime_ns != entry.mtime_ns):
                channel.send_control({"op": "error", "why": f"“{entry.path}” changed after it was copied; copy it again"})
                return
            while left:
                chunk = source.read(min(CHUNK_BYTES, left))
                if not chunk:
                    channel.send_control({"op": "error", "why": f"“{entry.path}” got shorter while it was being sent"})
                    return
                digest.update(chunk)
                channel.send(KIND_DATA, chunk)
                left -= len(chunk)
                progress.add(len(chunk))
        channel.send_control({"op": "done", "sha256": digest.hexdigest()})


class _Sent:
    """Bytes sent on one connection, reported at most every PROGRESS_SECONDS (and at the start)."""

    def __init__(self, server, offer):
        self._server, self._offer = server, offer
        self.bytes = 0
        self._last = None

    def add(self, count):
        self.bytes += count
        now = time.monotonic()
        if self._last is None or now - self._last >= PROGRESS_SECONDS or self.bytes == self._offer.total_bytes:
            self._last = now
            self._server._tell(self._offer, "sending", self.bytes)


# The receiver

def fetch(host, manifest, drop_folder, max_bytes, progress=None, cancel=None, today=None, connect=socket.create_connection,
          mark=None):
    """Fetch the files a `files` manifest (protocol.read_files' dict) names from `host`, into
    `drop_folder`/<yyyy-mm-dd>/, and return the full paths of the top-level items as they landed
    (each renamed "name (2)" and so on when the name is taken). `progress(done_bytes, total_bytes,
    path)` is called as bytes arrive; setting `cancel` (a threading.Event) stops the transfer.
    Raises TransferCancelled or TransferError; either way nothing is left behind."""
    cancel = cancel or threading.Event()
    total = manifest["total_bytes"]
    if total > max_bytes:
        raise TransferError(f"{_size(total)} is over this PC's limit of {_size(max_bytes)}")
    os.makedirs(drop_folder, exist_ok=True)
    free = shutil.disk_usage(drop_folder).free
    if total + DISK_HEADROOM_BYTES > free:
        raise TransferError(f"{_size(total)} does not fit: {_size(free)} is free on that drive")
    staging = os.path.join(drop_folder, STAGING, manifest["transfer"].hex())
    # Partial files live beside the staging tree, named by their place in the listing, so no
    # listed name (however crafted, whatever its case) can ever be one of them.
    parts = staging + ".parts"
    for folder in (staging, parts):
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
    finished = threading.Event()
    try:
        try:
            sock = connect((host, manifest["port"]), timeout=HANDSHAKE_SECONDS)
        except OSError as exc:
            raise TransferError("the other machine could not be reached for the files; "
                                "check that its firewall allows TCP %d" % manifest["port"]) from exc
        with sock:
            threading.Thread(target=_close_on_cancel, args=(cancel, finished, sock), daemon=True).start()
            try:
                _pull(sock, manifest, staging, max_bytes, progress, cancel, mark, parts)
            except (OSError, TransferError) as exc:
                if cancel.is_set():
                    raise TransferCancelled("the transfer was cancelled") from exc
                if isinstance(exc, TransferError):
                    raise
                raise TransferError("the file connection to the other machine was lost") from exc
            finally:
                finished.set()
        _check_staged(staging, manifest)
        return _place(staging, manifest["names"], drop_folder, today)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(parts, ignore_errors=True)
        _remove_if_empty(os.path.join(drop_folder, STAGING))


def _close_on_cancel(cancel, finished, sock):
    while not finished.is_set():
        if cancel.wait(0.1):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return


def _pull(sock, manifest, staging, max_bytes, progress, cancel, mark=None, parts=None):
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    transfer, ticket = manifest["transfer"], manifest["ticket"]
    random_r = secrets.token_bytes(RANDOM_SIZE)
    sock.sendall(MAGIC + transfer + random_r)
    head = _recv_exact(sock, len(MAGIC) + RANDOM_SIZE)
    if head[:len(MAGIC)] != MAGIC:
        raise TransferError("the other machine is not offering these files any more")
    random_s = head[len(MAGIC):]
    channel = _Channel(sock, _key(ticket, transfer, random_r, random_s, TO_SENDER),
                       _key(ticket, transfer, random_r, random_s, TO_RECEIVER))
    sock.settimeout(SOCKET_SECONDS)
    entries = _receive_listing(channel, manifest, max_bytes)
    done, total = 0, manifest["total_bytes"]
    if progress:
        progress(0, total, None)
    for index, entry in enumerate(entries):
        target = os.path.join(staging, *entry["path"].split("/"))
        if entry.get("dir"):
            os.makedirs(target, exist_ok=True)
            continue
        if cancel.is_set():
            raise TransferCancelled("the transfer was cancelled")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        channel.send_control({"op": "get", "index": index})
        part = os.path.join(parts or (staging + ".parts"), str(index))
        done = _receive_file(channel, entry, target, done, total, progress, cancel, mark, part)
    channel.send_control({"op": "bye"})


def _receive_listing(channel, manifest, max_bytes):
    names = {name.casefold() for name in manifest["names"]}
    entries, seen = [], set()
    channel.send_control({"op": "list"})
    while True:
        kind, message = channel.recv()
        if kind != KIND_CONTROL:
            raise TransferError("the other machine sent file bytes before the listing")
        if message["op"] == "end":
            break
        if message["op"] != "entries" or not isinstance(message.get("entries"), list):
            raise TransferError("the other machine sent a malformed listing")
        for entry in message["entries"]:
            if not isinstance(entry, dict):
                raise TransferError("the other machine sent a malformed listing")
            path = entry.get("path")
            if not protocol.valid_relative_path(path) or path.split("/")[0].casefold() not in names or path.casefold() in seen:
                raise TransferError("the other machine listed a file outside what it offered")
            seen.add(path.casefold())
            if entry.get("dir") is True and set(entry) == {"path", "dir"}:
                entries.append({"path": path, "dir": True})
            elif set(entry) == {"path", "size"} and protocol._int(entry["size"], 0, protocol.MAX_SAFE_INTEGER):
                entries.append({"path": path, "size": entry["size"]})
            else:
                raise TransferError("the other machine sent a malformed listing")
            if len(entries) > protocol.FILES_MAX_COUNT * 2:
                raise TransferError("the other machine listed too many files")
    files = [entry for entry in entries if not entry.get("dir")]
    total = sum(entry["size"] for entry in files)
    if len(files) != manifest["count"] or total != manifest["total_bytes"]:
        raise TransferError("the files changed on the other machine after they were copied; copy them again")
    if total > max_bytes:
        raise TransferError(f"{_size(total)} is over this PC's limit of {_size(max_bytes)}")
    if message.get("count") != manifest["count"] or message.get("total_bytes") != total:
        raise TransferError("the other machine's listing does not add up")
    return entries


def _receive_file(channel, entry, target, done, total, progress, cancel, mark=None, part=None):
    digest, left = hashlib.sha256(), entry["size"]
    part = part or target + ".part"
    os.makedirs(os.path.dirname(part), exist_ok=True)
    with open(part, "xb") as out:
        while True:
            kind, body = channel.recv()
            if kind == KIND_DATA:
                if len(body) > left:
                    raise TransferError(f"“{entry['path']}” arrived longer than listed")
                out.write(body)
                digest.update(body)
                left -= len(body)
                done += len(body)
                if progress:
                    progress(done, total, entry["path"])
                if cancel.is_set():
                    raise TransferCancelled("the transfer was cancelled")
                continue
            op = body["op"]
            if op == "error" and isinstance(body.get("why"), str):
                raise TransferError(body["why"][:300])
            if op != "done" or left:
                raise TransferError(f"“{entry['path']}” arrived incomplete")
            if body.get("sha256") != digest.hexdigest():
                raise TransferError(f"“{entry['path']}” arrived damaged")
            break
    if mark is not None:
        mark(part)
    _move_no_replace(part, target, entry["path"])
    return done


def _move_no_replace(source, target, shown):
    """Rename `source` to `target`, failing rather than overwriting anything already there: two
    listed names the drive treats as one (case, 8.3 short names) end the transfer, never lose a file."""
    try:
        if os.name == "nt":
            os.rename(source, target)  # Windows refuses an existing target
        else:
            os.link(source, target)    # refuses an existing target; then drop the old name
            os.unlink(source)
    except FileExistsError as exc:
        raise TransferError(f"“{shown}” clashes with another name in the same folder on this PC") from exc


def _check_staged(staging, manifest):
    """Before anything moves into place: exactly the listed number of files and bytes are there."""
    count = size = 0
    for root, _, files in os.walk(staging):
        for name in files:
            count += 1
            size += os.path.getsize(os.path.join(root, name))
    if count != manifest["count"] or size != manifest["total_bytes"]:
        raise TransferError("what arrived does not match what was listed; nothing was kept")


def _place(staging, names, drop_folder, today):
    day = (today or datetime.date.today()).isoformat()
    folder = os.path.join(drop_folder, day)
    os.makedirs(folder, exist_ok=True)
    _mark_as_ours(folder)
    landed = []
    for name in names:
        source = os.path.join(staging, name)
        if not os.path.exists(source):
            continue
        target = _free_name(folder, name, os.path.isdir(source))
        os.replace(source, target)
        landed.append(target)
    return landed


def _free_name(folder, name, is_dir):
    target = os.path.join(folder, name)
    if not os.path.exists(target):
        return target
    stem, ext = (name, "") if is_dir else os.path.splitext(name)
    number = 2
    while True:
        candidate = os.path.join(folder, f"{stem} ({number}){ext}")
        if not os.path.exists(candidate):
            return candidate
        number += 1


def _remove_if_empty(path):
    try:
        os.rmdir(path)
    except OSError:
        pass


def _size(count):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:,.0f} {unit}" if unit == "bytes" else f"{count:,.1f} {unit}"
        count /= 1024


# Received files on Windows

# What Edge writes on a download. With it SmartScreen asks before a received program runs and
# Office opens a received document in Protected View; it survives the move out of the drop folder.
ZONE_IDENTIFIER = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=about:internet\r\n"


def mark_from_another_computer(path) -> bool:
    """Give `path` the Windows mark of the web (an NTFS Zone.Identifier stream). False when it
    could not be written, off Windows or on a drive without streams (FAT32, some network shares);
    the file is still fine, only unmarked."""
    if os.name != "nt":
        return False
    try:
        with open(path + ":Zone.Identifier", "w", encoding="ascii", newline="") as stream:
            stream.write(ZONE_IDENTIFIER)
        return True
    except OSError:
        LOGGER.info("could not mark %s as from another computer", path)
        return False


_DAY_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}")
# A dated folder holding this file was made by Scotty; only those are ever cleared, so a folder
# of the person's own that happens to be named like a date is never touched.
OURS_MARKER = ".scotty-received"


def _mark_as_ours(folder):
    marker = os.path.join(folder, OURS_MARKER)
    if os.path.exists(marker):
        return
    try:
        with open(marker, "w", encoding="ascii") as out:
            out.write("Files Scotty received. Pasting moves them out; what is left is cleared after some days.\n")
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(marker, 0x2)  # hidden
    except OSError:
        LOGGER.info("could not mark %s as Scotty's", folder)


def clean_drop_folder(drop_folder, keep_days, today=None) -> int:
    """Remove what was received more than `keep_days` days ago and never pasted (pasting moves
    files out), and any empty dated folder before today. Only Scotty's own dated folders
    (yyyy-mm-dd) directly in `drop_folder` are touched, and stale staging from a transfer that
    died with the app; nothing else in the folder, and never through a link or junction. 0 keeps
    everything. Returns how many dated folders were removed; never raises."""
    removed = 0
    today = today or datetime.date.today()
    try:
        names = os.listdir(drop_folder)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(drop_folder, name)
        if not _DAY_FOLDER.fullmatch(name) or os.path.islink(path) or _is_junction(path) or not os.path.isdir(path):
            continue
        if not os.path.isfile(os.path.join(path, OURS_MARKER)):
            continue
        try:
            day = datetime.date.fromisoformat(name)
        except ValueError:
            continue
        try:
            if keep_days and (today - day).days > keep_days:
                shutil.rmtree(path)
                removed += 1
            elif day < today and os.listdir(path) == [OURS_MARKER]:
                shutil.rmtree(path)
                removed += 1
        except OSError:
            LOGGER.info("could not clear %s from the drop folder", path)
    staging = os.path.join(drop_folder, STAGING)
    if os.path.isdir(staging) and not os.path.islink(staging) and not _is_junction(staging):
        for name in os.listdir(staging):
            path = os.path.join(staging, name)
            try:
                if time.time() - os.path.getmtime(path) > 24 * 60 * 60:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
        _remove_if_empty(staging)
    return removed
