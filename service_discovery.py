"""
Service Discovery Module
Allows machines to broadcast their names and be discovered on the local network
"""
import socket
import struct
import threading
import json
import time
from typing import Dict, Optional, Callable


class ServiceDiscovery:
    MULTICAST_GROUP = '239.255.77.77'
    MULTICAST_PORT = 5007
    # Beacon every 1s and treat peers stale after 4s (faster discovery, proven to work)
    BEACON_INTERVAL = 1  # interval between beacons (seconds)
    TIMEOUT = 4  # timeout for stale peers (seconds)
    
    def __init__(self, machine_name: str, port: int, callback: Optional[Callable] = None, broadcast: bool = True, broadcast_only: bool = False):
        """
        Initialize service discovery
        
        Args:
            machine_name: Name to broadcast for this machine
            port: Port number where file transfer server is listening
            callback: Optional callback function when peers list changes
            broadcast: Whether to broadcast beacons (default True)
            broadcast_only: If True, force using UDP broadcast only (no multicast)
        """
        self.machine_name = machine_name
        self.port = port
        self.callback = callback
        self.broadcast = broadcast  # New parameter: whether to send beacons
        self.broadcast_only = broadcast_only
        self.running = False
        self.peers: Dict[str, dict] = {}  # {machine_name: {ip, port, last_seen}}
        self.local_ip = self._get_local_ip()
        
        # Threading
        self.beacon_thread = None
        self.listen_thread = None
        self.cleanup_thread = None
        self.lock = threading.Lock()
        # Keep references to sockets so we can close them on stop() to
        # immediately unblock threads waiting on recv/send.
        self._listen_sock = None
        self._beacon_sockets = []
        
    def start(self):
        """Start broadcasting and listening for peers"""
        if self.running:
            return
            
        self.running = True
        
        # Start beacon broadcaster only if broadcast is True
        if self.broadcast:
            self.beacon_thread = threading.Thread(target=self._broadcast_beacon, daemon=True)
            self.beacon_thread.start()
        
        # Start listener (always active)
        self.listen_thread = threading.Thread(target=self._listen_for_beacons, daemon=True)
        self.listen_thread.start()
        
        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_stale_peers, daemon=True)
        self.cleanup_thread.start()
        
    def stop(self):
        """Stop broadcasting and listening"""
        self.running = False
        # Close any open sockets to immediately unblock threads
        try:
            if self._listen_sock:
                try:
                    self._listen_sock.close()
                except Exception:
                    pass
                self._listen_sock = None
        except Exception:
            pass

        try:
            for s in list(self._beacon_sockets):
                try:
                    s.close()
                except Exception:
                    pass
            self._beacon_sockets.clear()
        except Exception:
            pass

        # Join threads with a short timeout to avoid long blocking
        if self.beacon_thread:
            self.beacon_thread.join(timeout=0.5)
        if self.listen_thread:
            self.listen_thread.join(timeout=0.5)
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=0.5)
            
    def get_peers(self) -> Dict[str, dict]:
        """Get current list of discovered peers"""
        with self.lock:
            # Include last_seen timestamp for richer UI (e.g., last-seen display)
            result = {}
            for name, info in self.peers.items():
                result[name] = {
                    'ip': info['ip'],
                    'port': info['port'],
                    'last_seen': info.get('last_seen', None)
                }
            return result
                   
    def get_peer_ip(self, machine_name: str) -> Optional[str]:
        """Get IP address for a specific machine name"""
        with self.lock:
            peer = self.peers.get(machine_name)
            return peer['ip'] if peer else None
            
    def _broadcast_beacon(self):
        """Broadcast this machine's presence via multicast and fallback to UDP broadcast"""
        message = json.dumps({
            'name': self.machine_name,
            'ip': self.local_ip,
            'port': self.port,
            'timestamp': time.time()
        })
        
        # If broadcast_only is requested, skip multicast entirely
        multicast_ok = False
        multicast_sock = None

        if not self.broadcast_only:
            # Try multicast first
            try:
                multicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                # Set multicast outgoing interface to the local IP to improve reliability
                try:
                    multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.local_ip))
                except Exception:
                    pass
                multicast_ok = True
            except Exception:
                multicast_ok = False

        # Prepare broadcast socket (works on many Windows networks)
        broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            broadcast_ok = True
        except Exception:
            broadcast_ok = False

        # remember sockets so stop() can close them
        try:
            if multicast_ok and multicast_sock:
                self._beacon_sockets.append(multicast_sock)
        except Exception:
            pass
        try:
            if broadcast_ok and broadcast_sock:
                self._beacon_sockets.append(broadcast_sock)
        except Exception:
            pass

        try:
            while self.running:
                msg_bytes = message.encode('utf-8')

                # Send via multicast if available and not forced to broadcast-only
                if multicast_ok and multicast_sock:
                    try:
                        multicast_sock.sendto(msg_bytes, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
                    except Exception:
                        multicast_ok = False

                # Send via UDP broadcast as primary fallback (or primary if broadcast_only)
                if broadcast_ok:
                    try:
                        broadcast_sock.sendto(msg_bytes, ('<broadcast>', self.MULTICAST_PORT))
                    except Exception:
                        broadcast_ok = False

                time.sleep(self.BEACON_INTERVAL)
        finally:
            # sockets may be closed by stop(); ensure they are removed
            try:
                if multicast_sock in self._beacon_sockets:
                    try:
                        multicast_sock.close()
                    except Exception:
                        pass
                    try:
                        self._beacon_sockets.remove(multicast_sock)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if broadcast_sock in self._beacon_sockets:
                    try:
                        broadcast_sock.close()
                    except Exception:
                        pass
                    try:
                        self._beacon_sockets.remove(broadcast_sock)
                    except Exception:
                        pass
            except Exception:
                pass

    def send_beacon_once(self):
        """Send a single beacon immediately (used to speed up manual refresh)."""
        message = json.dumps({
            'name': self.machine_name,
            'ip': self.local_ip,
            'port': self.port,
            'timestamp': time.time()
        })
        msg_bytes = message.encode('utf-8')

        # Try multicast if allowed
        if not self.broadcast_only:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                except Exception:
                    pass
                try:
                    sock.sendto(msg_bytes, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass
            except Exception:
                pass

        # Also send broadcast
        try:
            b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                b.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                pass
            try:
                b.sendto(msg_bytes, ('<broadcast>', self.MULTICAST_PORT))
            except Exception:
                pass
            try:
                b.close()
            except Exception:
                pass
        except Exception:
            pass
            
    def _listen_for_beacons(self):
        """Listen for beacons from other machines"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to the multicast port
        sock.bind(('', self.MULTICAST_PORT))
        # keep reference so stop() can close it and unblock recvfrom
        self._listen_sock = sock
        
        # Join multicast group on the specific local interface to avoid ambiguity.
        # If local_ip appears to be loopback or unknown, fall back to INADDR_ANY.
        try:
            if self.local_ip.startswith('127.') or self.local_ip == '0.0.0.0':
                # Use INADDR_ANY membership
                mreq = struct.pack('4sl', socket.inet_aton(self.MULTICAST_GROUP), socket.INADDR_ANY)
            else:
                mreq = struct.pack('4s4s', socket.inet_aton(self.MULTICAST_GROUP), socket.inet_aton(self.local_ip))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception:
            # Best-effort; if this fails we continue — broadcast fallback may still work.
            pass
        sock.settimeout(1.0)
        
        try:
            while self.running:
                try:
                    # If stop() closed the listen socket, exit loop
                    if not self.running or self._listen_sock is None:
                        break
                    try:
                        fd = sock.fileno()
                    except Exception:
                        break
                    if fd < 0:
                        break

                    data, addr = sock.recvfrom(1024)
                    message = json.loads(data.decode('utf-8'))
                    
                    # Don't add ourselves
                    if message['name'] == self.machine_name:
                        continue
                        
                    # Update peer information
                    with self.lock:
                        old_peers = set(self.peers.keys())
                        self.peers[message['name']] = {
                            'ip': message['ip'],
                            'port': message['port'],
                            'last_seen': time.time()
                        }
                        new_peers = set(self.peers.keys())
                        
                        # Trigger callback if peers changed
                        if old_peers != new_peers and self.callback:
                            self.callback()
                            
                except socket.timeout:
                    continue
                except OSError:
                    break
                except (json.JSONDecodeError, KeyError):
                    continue
                    
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self._listen_sock = None
            
    def _cleanup_stale_peers(self):
        """Remove peers that haven't been seen recently"""
        while self.running:
            time.sleep(self.BEACON_INTERVAL)
            current_time = time.time()
            
            with self.lock:
                old_peers = set(self.peers.keys())
                stale = [name for name, info in self.peers.items() 
                        if current_time - info['last_seen'] > self.TIMEOUT]
                
                for name in stale:
                    del self.peers[name]
                    
                new_peers = set(self.peers.keys())
                
                # Trigger callback if peers changed
                if old_peers != new_peers and self.callback:
                    self.callback()
                    
    def _get_local_ip(self) -> str:
        """Get local IP address"""
        # Try a few methods to determine a sensible non-loopback IPv4 address.
        # 1) Connect to a public IP (doesn't actually send packets) to learn the outbound IP.
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith('127.'):
                return ip
        except Exception:
            pass

        # 2) Try hostname resolution to get an IP assigned to this host
        try:
            host = socket.gethostname()
            addrs = socket.getaddrinfo(host, None, family=socket.AF_INET)
            for a in addrs:
                candidate = a[4][0]
                if candidate and not candidate.startswith('127.'):
                    return candidate
        except Exception:
            pass

        # 3) As a last resort, return 0.0.0.0 to indicate 'any interface' (better than loopback for multicast)
        return '0.0.0.0'


# Command-line test
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Service discovery test runner")
    parser.add_argument('machine_name', help='Machine name to broadcast')
    parser.add_argument('--port', type=int, default=5000, help='Port where receiver listens (default: 5000)')
    parser.add_argument('--broadcast-only', action='store_true', help='Force using UDP broadcast only (no multicast)')
    args = parser.parse_args()

    machine_name = args.machine_name

    def on_peers_changed():
        print(f"\nDiscovered peers: {discovery.get_peers()}")

    discovery = ServiceDiscovery(machine_name, args.port, callback=on_peers_changed, broadcast_only=args.broadcast_only)
    discovery.start()

    mode = 'broadcast-only' if args.broadcast_only else 'multicast+broadcast'
    print(f"Broadcasting as '{machine_name}' on port {args.port} (mode: {mode})...")
    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        discovery.stop()