"""Send 1 GB through Scotty's file channel over loopback, check it arrives identical, and time it.
Part of scripts/verify.sh; leaves nothing behind."""

import hashlib
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import filechannel, protocol  # noqa: E402

SIZE = 1024 ** 3


def digest(path):
    hashed = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def main():
    base = tempfile.mkdtemp(prefix="scotty-gb-")
    server = None
    try:
        source = os.path.join(base, "big.bin")
        block = os.urandom(8 << 20)
        with open(source, "wb") as out:
            for _ in range(SIZE // len(block)):
                out.write(block)
        server = filechannel.FileServer(host="127.0.0.1", port=0).start()
        wire = protocol.dumps_message(server.manifest(server.offer([source], allowed_host="127.0.0.1")))
        manifest = protocol.read_files(protocol.parse_message(wire))
        started = time.perf_counter()
        landed = filechannel.fetch("127.0.0.1", manifest, os.path.join(base, "drop"), 4 * SIZE)
        seconds = time.perf_counter() - started
        same = digest(source) == digest(landed[0])
        print(f"1 GB in {seconds:.1f} s ({SIZE / seconds / 1024 ** 2:.0f} MB/s); identical: {same}")
        return 0 if same else 1
    finally:
        if server is not None:
            server.close()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
