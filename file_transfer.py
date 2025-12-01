#!/usr/bin/env python3
"""
NetLink - Cross-platform File Transfer Application
Supports Windows, Linux, and macOS
"""
import argparse
import sys
from transfer_server import TransferServer
from transfer_client import TransferClient


def main():
    parser = argparse.ArgumentParser(
        description='NetLink - Cross-platform file transfer application',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Receive files:
    python file_transfer.py receive --port 5000
  
  Send a file:
    python file_transfer.py send --host 192.168.1.100 --port 5000 --file document.pdf
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Receive command
    receive_parser = subparsers.add_parser('receive', help='Start server to receive files')
    receive_parser.add_argument('--port', type=int, default=5000, help='Port to listen on (default: 5000)')
    receive_parser.add_argument('--output-dir', default='.', help='Directory to save received files (default: current directory)')
    
    # Send command
    send_parser = subparsers.add_parser('send', help='Send a file to a receiver')
    send_parser.add_argument('--host', required=True, help='IP address or hostname of the receiver')
    send_parser.add_argument('--port', type=int, default=5000, help='Port of the receiver (default: 5000)')
    send_parser.add_argument('--file', required=True, help='Path to the file to send')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        if args.command == 'receive':
            server = TransferServer(port=args.port, output_dir=args.output_dir)
            server.start()
        elif args.command == 'send':
            client = TransferClient(host=args.host, port=args.port)
            client.send_file(args.file)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()