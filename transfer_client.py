#!/usr/bin/env python3
"""
Transfer Client Module
Handles sending files to servers (single files, multiple files, or entire directories)
"""
import socket
import os
import struct
from pathlib import Path
import hashlib
import time


class TransferClient:
    BUFFER_SIZE = 4096
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        
    def send_file(self, filepath, progress_callback=None):
        """Send a file or directory to the server (backward compatible)"""
        filepath = Path(filepath)
        if filepath.is_dir():
            self.send_directory(filepath, progress_callback)
        else:
            self.send_single_file(filepath, progress_callback)
    
    def send_single_file(self, filepath, progress_callback=None):
        """Send a single file to the server"""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
            
        filesize = filepath.stat().st_size
        filename = filepath.name
        
        print(f"Sending: {filename} ({self._format_size(filesize)})")
        
        # Compute SHA256 digest first (needed for verification and resume negotiation)
        sha = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
        digest = sha.digest()

        # Try resumable protocol (magic 0xFFFF0003)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect((self.host, self.port))

            # Send magic header for resumable single-file protocol (0xFFFF0003)
            client_socket.sendall(struct.pack('!I', 0xFFFF0003))

            # Send filename length and filename
            filename_encoded = filename.encode('utf-8')
            client_socket.sendall(struct.pack('!I', len(filename_encoded)))
            client_socket.sendall(filename_encoded)

            # Send file size
            client_socket.sendall(struct.pack('!Q', filesize))

            # Send preferred chunk size
            preferred_chunk = 65536
            client_socket.sendall(struct.pack('!I', preferred_chunk))

            # Send sha256 (32 bytes)
            client_socket.sendall(digest)

            # Read server reply: current offset (8 bytes)
            offset_data = self._recv_exact(client_socket, 8)
            if not offset_data:
                raise Exception("Server did not reply with offset for resumable transfer")
            offset = struct.unpack('!Q', offset_data)[0]

            # Log offset negotiation for callers
            # Send the remaining bytes from offset
            sent = offset
            start_time = time.time()
            with open(filepath, 'rb') as f:
                f.seek(offset)
                while sent < filesize:
                    to_read = min(self.BUFFER_SIZE, filesize - sent)
                    data = f.read(to_read)
                    if not data:
                        break
                    client_socket.sendall(data)
                    sent += len(data)
                    # Progress indicator with speed/ETA
                    elapsed = max(0.001, time.time() - start_time)
                    speed = sent / elapsed  # bytes/sec
                    remaining = max(0, filesize - sent)
                    eta = int(remaining / speed) if speed > 0 else None
                    progress = (sent / filesize) * 100
                    print(f"\rProgress: {progress:.1f}% ({self._format_size(sent)}/{self._format_size(filesize)})", end='')
                    if progress_callback:
                        try:
                            progress_callback(sent, filesize, speed, eta)
                        except TypeError:
                            # fallback to older signature
                            progress_callback(sent, filesize)

            print()

            # Wait for final acknowledgment
            ack = client_socket.recv(2)
            if ack != b'OK':
                raise Exception("Server reported error after transfer (checksum mismatch?)")

            print("File sent successfully!")
            # Return offset negotiated (0 if fresh) and success flag
            return offset, True

    def _recv_exact(self, sock, size):
        """Helper to receive exact bytes from a connected socket (client-side)."""
        data = b''
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data
    
    def send_multiple_files(self, filepaths, progress_callback=None):
        """Send multiple files to the server"""
        filepaths = [Path(f) for f in filepaths]
        
        # Verify all files exist
        for filepath in filepaths:
            if not filepath.exists():
                raise FileNotFoundError(f"File not found: {filepath}")
        
        # Calculate total size
        total_size = sum(f.stat().st_size for f in filepaths if f.is_file())
        
        print(f"Sending {len(filepaths)} file(s) - Total size: {self._format_size(total_size)}")
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect((self.host, self.port))
            
            # Send magic header for multi-file protocol (0xFFFF0002)
            client_socket.sendall(struct.pack('!I', 0xFFFF0002))
            
            # Send number of files
            client_socket.sendall(struct.pack('!I', len(filepaths)))
            
            sent_total = 0
            start_time = time.time()
            for filepath in filepaths:
                filesize = filepath.stat().st_size
                filename = filepath.name
                
                print(f"\nSending: {filename} ({self._format_size(filesize)})")
                
                # Send filename length and filename
                filename_encoded = filename.encode('utf-8')
                client_socket.sendall(struct.pack('!I', len(filename_encoded)))
                client_socket.sendall(filename_encoded)
                
                # Send file size
                client_socket.sendall(struct.pack('!Q', filesize))
                
                # Send file content
                sent = 0
                with open(filepath, 'rb') as f:
                    while sent < filesize:
                        data = f.read(self.BUFFER_SIZE)
                        if not data:
                            break
                        client_socket.sendall(data)
                        sent += len(data)
                        sent_total += len(data)

                        # Progress indicator with speed/ETA (per-file + total)
                        elapsed = max(0.001, time.time() - start_time)
                        speed = sent_total / elapsed
                        remaining_total = max(0, total_size - sent_total)
                        total_eta = int(remaining_total / speed) if speed > 0 else None

                        remaining_file = max(0, filesize - sent)
                        file_eta = int(remaining_file / speed) if speed > 0 else None

                        progress = (sent / filesize) * 100
                        total_progress = (sent_total / total_size) * 100
                        print(f"\rFile: {progress:.1f}% | Total: {total_progress:.1f}% ({self._format_size(sent_total)}/{self._format_size(total_size)})", end='')
                        if progress_callback:
                            try:
                                # signature: sent, total, speed, eta, total_sent, total_size, total_eta, filename
                                progress_callback(sent, filesize, speed, file_eta, sent_total, total_size, total_eta, filename)
                            except TypeError:
                                try:
                                    progress_callback(sent_total, total_size, speed, total_eta)
                                except TypeError:
                                    progress_callback(sent_total, total_size)
            
            print("\n")
            
            # Wait for acknowledgment
            ack = client_socket.recv(2)
            if ack != b'OK':
                raise Exception("Server did not acknowledge receipt")
                
            print(f"All {len(filepaths)} file(s) sent successfully!")
    
    def send_directory(self, dirpath, progress_callback=None):
        """Send entire directory recursively to the server"""
        dirpath = Path(dirpath)
        if not dirpath.is_dir():
            raise NotADirectoryError(f"Not a directory: {dirpath}")
        
        # Collect all files recursively
        all_files = list(dirpath.rglob('*'))
        files = [f for f in all_files if f.is_file()]
        
        if not files:
            raise FileNotFoundError(f"No files found in directory: {dirpath}")
        
        # Calculate total size
        total_size = sum(f.stat().st_size for f in files)
        
        print(f"Sending directory: {dirpath.name}")
        print(f"Files: {len(files)} - Total size: {self._format_size(total_size)}")
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect((self.host, self.port))
            
            # Send magic header for multi-file protocol (0xFFFF0002)
            client_socket.sendall(struct.pack('!I', 0xFFFF0002))
            
            # Send number of files
            client_socket.sendall(struct.pack('!I', len(files)))
            
            sent_total = 0
            start_time = time.time()
            for filepath in files:
                filesize = filepath.stat().st_size
                # Preserve directory structure relative to parent
                relative_path = filepath.relative_to(dirpath.parent)
                filename = str(relative_path).replace('\\', '/')  # Normalize path separators
                
                print(f"\nSending: {filename} ({self._format_size(filesize)})")
                
                # Send filename length and filename
                filename_encoded = filename.encode('utf-8')
                client_socket.sendall(struct.pack('!I', len(filename_encoded)))
                client_socket.sendall(filename_encoded)
                
                # Send file size
                client_socket.sendall(struct.pack('!Q', filesize))
                
                # Send file content
                sent = 0
                with open(filepath, 'rb') as f:
                    while sent < filesize:
                        data = f.read(self.BUFFER_SIZE)
                        if not data:
                            break
                        client_socket.sendall(data)
                        sent += len(data)
                        sent_total += len(data)

                        # Progress indicator with speed/ETA
                        elapsed = max(0.001, time.time() - start_time)
                        speed = sent_total / elapsed
                        remaining = max(0, total_size - sent_total)
                        eta = int(remaining / speed) if speed > 0 else None
                        progress = (sent / filesize) * 100
                        total_progress = (sent_total / total_size) * 100
                        print(f"\rFile: {progress:.1f}% | Total: {total_progress:.1f}% ({self._format_size(sent_total)}/{self._format_size(total_size)})", end='')
                        if progress_callback:
                            try:
                                progress_callback(sent_total, total_size, speed, eta)
                            except TypeError:
                                progress_callback(sent_total, total_size)
            
            print("\n")
            
            # Wait for acknowledgment
            ack = client_socket.recv(2)
            if ack != b'OK':
                raise Exception("Server did not acknowledge receipt")
                
            print(f"Directory sent successfully ({len(files)} file(s))!")
            
    def _format_size(self, size):
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"