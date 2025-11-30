# File Transfer App

A simple, cross-platform command-line application for transferring files between computers over a local network.

## Features

- ✅ Cross-platform support (Windows, Linux, macOS)
- ✅ No external dependencies (uses Python standard library only)
- ✅ Graphical user interface (GUI) and command-line interface (CLI)
- ✅ **Service discovery**: Find machines by name instead of IP address
- ✅ **Multiple file transfer**: Send multiple files in one go
- ✅ **Directory transfer**: Send entire folders with directory structure
- ✅ Progress indicator during transfer
- ✅ TCP socket-based transfer for reliability
- ✅ Human-readable file size display

## Requirements

- Python 3.6 or higher (no additional packages required)

## Installation

1. Clone or download this repository
2. No additional installation required - uses only Python standard library

## Usage

### GUI Mode (Recommended)

For a user-friendly graphical interface:

```bash
python file_transfer_gui.py
```

The GUI provides:
- **Send File tab**: 
 - **Send Files tab**: 
  - Automatically discover machines on your network by name
  - Or manually enter receiver's IP address
  - Select **multiple files** to send together
  - Or select **folders** to send with directory structure
  - Real-time progress indicator
  - View transfer log
- **Receive Files tab**: 
 - **Receive Files tab**: 
  - Give your machine a friendly name for others to find
  - Start/stop the receiver
  - Choose output directory (files are auto-organized if from folders)
  - See your IP address
- Real-time transfer logs
- Progress indicators
- Easy file and directory browsing

### Command-Line Mode

#### Receiving Files

On the computer that will receive the file, start the server:

```bash
python file_transfer.py receive --port 5000
```

Optional arguments:
- `--port`: Port to listen on (default: 5000)
- `--output-dir`: Directory to save received files (default: current directory)

Example with custom output directory:
```bash
python file_transfer.py receive --port 5000 --output-dir ./received_files
```

#### Sending Files

On the computer that will send the file:

```bash
python file_transfer.py send --host 192.168.1.100 --port 5000 --file document.pdf
```

Required arguments:
- `--host`: IP address or hostname of the receiving computer
- `--file`: Path to the file you want to send

Optional arguments:
- `--port`: Port of the receiver (default: 5000)

## How It Works

### Service Discovery

The application automatically discovers other machines on your network using UDP multicast/broadcast:
- When you open the GUI, it broadcasts a beacon announcing your machine name and receive port
- Other machines on the network also broadcast their beacons
- The list of machines updates in real-time as they are discovered
- If automatic discovery fails, you can manually enter IP addresses instead

**Discovery operates on port 5007 (UDP)** - Make sure your firewall allows outgoing and incoming UDP on this port.

### File Transfer Process

1. The receiving computer starts a server that listens for incoming connections
2. The sending computer connects to the server and transmits the file
3. The transfer includes:
   - Filename
   - File size
   - File contents
   - Progress indicator
   - Acknowledgment upon completion

## Finding Your IP Address

### Windows
```powershell
ipconfig
```
Look for "IPv4 Address"

### Linux/macOS
```bash
ip addr show    # Linux
ifconfig        # macOS/Linux
```
Look for "inet" address (usually 192.168.x.x or 10.x.x.x for local networks)

## Network Configuration

- Ensure both computers are on the same network (or have network connectivity)
- If you have a firewall enabled, you may need to allow incoming connections on the chosen port
- For security reasons, this application is designed for trusted local networks only

## Security Notes

⚠️ **Important**: This is a basic file transfer tool designed for use on trusted local networks. It does not include:
- Encryption
- Authentication
- Authorization

Do not use this over untrusted networks or the internet without additional security measures.

## Examples

### Example 1: Transfer a document to another computer on your home network

**Computer A (Receiver - IP: 192.168.1.100):**
```bash
python file_transfer.py receive --port 5000
```

**Computer B (Sender):**
```bash
python file_transfer.py send --host 192.168.1.100 --port 5000 --file report.pdf
```

### Example 2: Organize received files in a specific folder

**Receiver:**
```bash
python file_transfer.py receive --port 8080 --output-dir ~/Downloads/transfers
```

**Sender:**
```bash
python file_transfer.py send --host 192.168.1.100 --port 8080 --file vacation_photos.zip
```

## Troubleshooting

### Discovery Issues (Machines Not Found)

If the GUI is not showing other machines in the "Discovered Machines" list:

1. **Check your network**
   - Ensure all computers are on the same local network (same WiFi or Ethernet subnet)
   - Check IP addresses are in same range (e.g., 192.168.x.x)

2. **Run the Discovery Diagnostic Tool**
   - Open the GUI and go to **Help → Discovery Diagnostics**
   - This shows your network status and which machines are visible
   - Or run: `python test_network_discovery.py`

3. **Firewall Settings**
   - The app uses UDP port 5007 for discovery
   - Windows Firewall: Allow the app through firewall
   - Check if your network is set as "Private" on Windows (not "Public")
   - Some corporate networks block multicast/broadcast - use Manual Connection instead

4. **Virtual Networks / VPN**
   - If using VPN or virtual network adapters, discovery may not work
   - Use **Manual Connection** to enter IP directly instead

5. **As a Fallback**
   - Use the **Manual Connection** feature in the GUI
   - Click "Advanced → Manual Connection..." and enter the IP address directly
   - Or find the IP address using:
     - **Windows**: `ipconfig` command (look for "IPv4 Address")
     - **Linux/macOS**: `ip addr` or `ifconfig` (look for "inet")

### Other Connection Issues

**Connection refused:**
- Ensure the receiver is running before attempting to send
- Verify the IP address is correct
- Check firewall settings on both computers
- Ensure both computers are on the same network

**File not found:**
- Verify the file path is correct
- Use absolute paths if relative paths aren't working

**Permission denied:**
- Ensure you have read permissions for the file you're sending
- Ensure you have write permissions in the output directory

## License

This project is open source and available for personal and commercial use.
## Author

Created by: Scorpionziky89

for any issues If you encounter any problems,bugs or have any questions, 
please contact me at scorpionziky89@gmail.com 