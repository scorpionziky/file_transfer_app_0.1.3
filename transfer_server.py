"""
Transfer Server Module
Handles receiving files from clients (single files, multiple files, or entire directories)
"""
import socket
import os
import struct
from pathlib import Path
import hashlib


class TransferServer:
    BUFFER_SIZE = 4096
    
    def __init__(self, port=5000, output_dir='.'):
        self.port = port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def start(self):
        """Start the server and listen for incoming connections"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('0.0.0.0', self.port))
            server_socket.listen(1)
            
            print(f"Server listening on port {self.port}")
            print(f"Files will be saved to: {self.output_dir.absolute()}")
            print("Waiting for connections...")
            
            while True:
                try:
                    conn, addr = server_socket.accept()
                    print(f"\nConnection from {addr[0]}:{addr[1]}")
                    result = self._receive_files(conn)
                    # Do not return here; keep server running to accept further connections.
                    if result:
                        print(f"Received result: {result}")
                except Exception as e:
                    print(f"Error handling connection: {e}")
    
    def _receive_files(self, conn):
        """Receive file(s) from the connected client"""
        try:
            # Read magic header to determine protocol version
            print("[DEBUG] _receive_files: waiting for 4-byte magic header")
            magic_data = self._recv_exact(conn, 4)
            if magic_data is None or not magic_data:
                print("[DEBUG] _receive_files: magic header not received")
                return
            
            magic = struct.unpack('!I', magic_data)[0]
            print(f"[DEBUG] _receive_files: magic header = 0x{magic:08X}")
            
            if magic == 0xFFFF0001:
                # Single-file protocol
                print("[DEBUG] _receive_files: detected SINGLE-FILE protocol")
                return self._receive_files_single(conn)
            elif magic == 0xFFFF0002:
                # Multi-file protocol
                print("[DEBUG] _receive_files: detected MULTI-FILE protocol")
                return self._receive_files_multi(conn)
            elif magic == 0xFFFF0003:
                # Resumable single-file protocol
                print("[DEBUG] _receive_files: detected RESUMABLE-SINGLE protocol")
                return self._receive_files_resumable_single(conn)
            else:
                print(f"[ERROR] _receive_files: unknown magic header 0x{magic:08X}")
                return None
                
        except Exception as e:
            print(f"\nError receiving files: {e}")
            return None
        finally:
            conn.close()

    def _receive_files_resumable_single(self, conn):
        """Receive a single file with resume support.

        Protocol (client -> server):
        - filename_len (4 bytes !I)
        - filename (utf-8)
        - filesize (8 bytes !Q)
        - chunk_size (4 bytes !I)  # suggested chunk size client will use
        - sha256 (32 bytes raw)
        Server replies with current_offset (8 bytes !Q).
        Client then sends remaining bytes starting at offset. After full transfer,
        server verifies SHA256 and replies b'OK' or b'ER'.
        """
        try:
            # Receive filename length
            filename_len_data = self._recv_exact(conn, 4)
            if not filename_len_data:
                return None
            filename_len = struct.unpack('!I', filename_len_data)[0]

            # Receive filename
            filename_data = self._recv_exact(conn, filename_len)
            if not filename_data:
                return None
            filename = filename_data.decode('utf-8')

            # Receive filesize
            filesize_data = self._recv_exact(conn, 8)
            if not filesize_data:
                return None
            filesize = struct.unpack('!Q', filesize_data)[0]

            # Receive chunk_size
            chunk_size_data = self._recv_exact(conn, 4)
            if not chunk_size_data:
                return None
            chunk_size = struct.unpack('!I', chunk_size_data)[0]

            # Receive expected sha256 (32 bytes)
            sha256_data = self._recv_exact(conn, 32)
            if not sha256_data:
                return None
            expected_digest = sha256_data  # raw bytes

            print(f"[DEBUG] Resumable receive: {filename} size={filesize} chunk={chunk_size}")

            # Prepare output paths
            output_path = self.output_dir / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path = output_path.with_suffix(output_path.suffix + '.partial')

            # If partial file exists but is larger than expected, remove it
            offset = 0
            if partial_path.exists():
                try:
                    existing_size = partial_path.stat().st_size
                    if existing_size > filesize:
                        partial_path.unlink()
                    else:
                        offset = existing_size
                except Exception:
                    offset = 0

            # Send current offset to client
            try:
                conn.sendall(struct.pack('!Q', offset))
            except Exception:
                return None

            # Open partial file for append and receive remaining bytes
            received = offset
            with open(partial_path, 'ab') as f:
                while received < filesize:
                    to_read = min(self.BUFFER_SIZE, filesize - received)
                    data = conn.recv(to_read)
                    if not data:
                        # Connection closed unexpectedly; leave partial file
                        break
                    f.write(data)
                    received += len(data)
                    # Optional progress print
                    try:
                        progress = (received / filesize) * 100
                        print(f"\rProgress: {progress:.1f}% ({self._format_size(received)}/{self._format_size(filesize)})", end='')
                    except Exception:
                        pass

            # If we didn't get all bytes, just return (client may resume later)
            if received < filesize:
                print("\nPartial transfer saved. Waiting for resume...")
                return None

            print(f"\nAll bytes received for {filename}. Verifying SHA256...")

            # Compute SHA256 of partial file
            h = hashlib.sha256()
            with open(partial_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            digest = h.digest()

            if digest == expected_digest:
                # Rename partial to final filename (overwrite if exists)
                try:
                    if output_path.exists():
                        output_path.unlink()
                    partial_path.replace(output_path)
                except Exception as e:
                    print(f"Error renaming partial file: {e}")
                    conn.sendall(b'ER')
                    return None

                print(f"File saved to: {output_path.absolute()}")
                conn.sendall(b'OK')
                return filename, filesize
            else:
                print("SHA256 mismatch: transfer corrupted")
                conn.sendall(b'ER')
                # leave partial file for inspection/resume
                return None

        except Exception as e:
            print(f"\nError receiving resumable file: {e}")
            return None

    def _receive_files_multi(self, conn):
        """Receive multiple files using multi-file protocol"""
        try:
            # Read number of files
            file_count_data = self._recv_exact(conn, 4)
            if not file_count_data:
                return None
            file_count = struct.unpack('!I', file_count_data)[0]
            print(f"Receiving {file_count} file(s)...")
            
            received_files = []
            for i in range(file_count):
                result = self._receive_single_file(conn, file_index=i+1, total_files=file_count)
                if result:
                    received_files.append(result)
            
            # Send acknowledgment
            conn.sendall(b'OK')
            
            return received_files[0] if received_files else None
            
        except Exception as e:
            print(f"\nError receiving multiple files: {e}")
            return None

    def _receive_files_single(self, conn):
        """Receive single file using single-file protocol"""
        try:
            # Receive filename length (4 bytes)
            filename_len_data = self._recv_exact(conn, 4)
            if not filename_len_data:
                print("[DEBUG] _receive_files_single: filename_len_data is None")
                return None
            filename_len = struct.unpack('!I', filename_len_data)[0]
            print(f"[DEBUG] _receive_files_single: filename_len = {filename_len}")
            
            # Receive filename
            filename_data = self._recv_exact(conn, filename_len)
            if not filename_data:
                print("[DEBUG] _receive_files_single: filename_data is None")
                return None
            filename = filename_data.decode('utf-8')
            print(f"[DEBUG] _receive_files_single: filename = {filename}")
            
            # Receive file size (8 bytes)
            filesize_data = self._recv_exact(conn, 8)
            if not filesize_data:
                print("[DEBUG] _receive_files_single: filesize_data is None")
                return None
            filesize = struct.unpack('!Q', filesize_data)[0]
            print(f"[DEBUG] _receive_files_single: filesize = {filesize}")
            
            print(f"Receiving: {filename} ({self._format_size(filesize)})")
            
            # Receive file content
            output_path = self.output_dir / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            received = 0
            with open(output_path, 'wb') as f:
                while received < filesize:
                    chunk_size = min(self.BUFFER_SIZE, filesize - received)
                    data = conn.recv(chunk_size)
                    if not data:
                        print("[DEBUG] _receive_files_single: recv returned no data (connection closed?)")
                        break
                    f.write(data)
                    received += len(data)
                    
                    # Progress indicator
                    progress = (received / filesize) * 100
                    print(f"\rProgress: {progress:.1f}% ({self._format_size(received)}/{self._format_size(filesize)})", end='')
            
            print(f"\nFile saved to: {output_path.absolute()}")
            
            # Send acknowledgment
            conn.sendall(b'OK')
            
            return filename, filesize
            
        except Exception as e:
            print(f"\nError receiving file: {e}")
            return None

    def _receive_file(self, conn):
        """Backward-compatible alias for single-file receiver.

        Some GUI code expects a `_receive_file` method on the server
        instance. Delegate to `_receive_files` which already handles
        single-file and multi-file protocols.
        """
        return self._receive_files(conn)
    
    def _receive_single_file(self, conn, file_index=1, total_files=1):
        """Receive a single file from the connection"""
        try:
            # Receive filename length (4 bytes)
            filename_len_data = self._recv_exact(conn, 4)
            if not filename_len_data:
                return None
            filename_len = struct.unpack('!I', filename_len_data)[0]
            
            # Receive filename
            filename_data = self._recv_exact(conn, filename_len)
            if not filename_data:
                return None
            filename = filename_data.decode('utf-8')
            
            # Receive file size (8 bytes)
            filesize_data = self._recv_exact(conn, 8)
            if not filesize_data:
                return None
            filesize = struct.unpack('!Q', filesize_data)[0]
            
            # Show progress with file count if multiple
            if total_files > 1:
                print(f"\n[{file_index}/{total_files}] Receiving: {filename} ({self._format_size(filesize)})")
            else:
                print(f"Receiving: {filename} ({self._format_size(filesize)})")
            
            # Receive file content
            output_path = self.output_dir / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            received = 0
            with open(output_path, 'wb') as f:
                while received < filesize:
                    chunk_size = min(self.BUFFER_SIZE, filesize - received)
                    data = conn.recv(chunk_size)
                    if not data:
                        break
                    f.write(data)
                    received += len(data)
                    
                    # Progress indicator
                    progress = (received / filesize) * 100
                    print(f"\rProgress: {progress:.1f}% ({self._format_size(received)}/{self._format_size(filesize)})", end='')
            
            print(f"\nFile saved to: {output_path.absolute()}")
            
            return filename, filesize
            
        except Exception as e:
            print(f"\nError receiving file: {e}")
            return None
    
    def _recv_exact(self, conn, size):
        """Receive exact amount of bytes"""
        data = b''
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data
    
    def _format_size(self, size):
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"