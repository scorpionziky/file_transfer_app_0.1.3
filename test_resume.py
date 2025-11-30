#!/usr/bin/env python3
import threading
import time
import os
import socket
import struct
import hashlib
from pathlib import Path

from transfer_server import TransferServer
from transfer_client import TransferClient


def make_test_file(path, size=200_000):
    data = os.urandom(size)
    with open(path, 'wb') as f:
        f.write(data)
    h = hashlib.sha256()
    h.update(data)
    return h.digest()


def partial_send(host, port, filepath, send_bytes):
    """Open a socket and perform the resumable-header + partial data send, then close."""
    filepath = Path(filepath)
    filesize = filepath.stat().st_size
    filename = filepath.name

    # compute sha
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    digest = h.digest()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        # magic for resumable
        s.sendall(struct.pack('!I', 0xFFFF0003))
        fn_enc = filename.encode('utf-8')
        s.sendall(struct.pack('!I', len(fn_enc)))
        s.sendall(fn_enc)
        s.sendall(struct.pack('!Q', filesize))
        s.sendall(struct.pack('!I', 65536))
        s.sendall(digest)

        # read server offset
        off_data = recv_exact(s, 8)
        if not off_data:
            print('No offset reply')
            return
        offset = struct.unpack('!Q', off_data)[0]
        print('Server replied offset =', offset)

        # send `send_bytes` bytes from file starting at offset
        sent = 0
        with open(filepath, 'rb') as f:
            f.seek(offset)
            while sent < send_bytes:
                to_read = min(4096, send_bytes - sent)
                chunk = f.read(to_read)
                if not chunk:
                    break
                s.sendall(chunk)
                sent += len(chunk)
        print('Partial send done, closing socket')
        # close and return


def recv_exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


if __name__ == '__main__':
    host = '127.0.0.1'
    port = 5100
    work = Path('test_output_resume')
    if work.exists():
        # clean
        for p in work.iterdir():
            try:
                p.unlink()
            except Exception:
                pass
    else:
        work.mkdir()

    src = Path('test_resume_source.bin')
    digest = make_test_file(src, size=200_000)
    print('Test file and digest prepared')

    server = TransferServer(port=port, output_dir=str(work))
    t = threading.Thread(target=server.start, daemon=True)
    t.start()

    time.sleep(0.5)

    # send half of the file using low-level socket to simulate interruption
    partial_send(host, port, src, send_bytes=80_000)

    time.sleep(0.5)

    # now resume with TransferClient
    client = TransferClient(host, port)
    print('Invoking client.send_single_file to resume...')
    client.send_single_file(str(src))

    # verify
    out_file = work / src.name
    if not out_file.exists():
        print('FAIL: output file not created')
        raise SystemExit(2)

    # compute sha
    h2 = hashlib.sha256()
    with open(out_file, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h2.update(chunk)
    if h2.digest() == digest:
        print('PASS: resumed transfer verified (SHA256 match)')
        # cleanup
        try:
            src.unlink()
        except Exception:
            pass
        raise SystemExit(0)
    else:
        print('FAIL: checksum mismatch')
        raise SystemExit(3)
