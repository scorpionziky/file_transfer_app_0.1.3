# NetLink - File Transfer App

A simple, cross-platform command-line application for transferring files between computers over a local network.

## Features

✅ Cross-platform support (Windows, Linux, macOS)

✅ No external dependencies (uses Python standard library only)

✅ Graphical user interface (GUI) and command-line interface (CLI)

✅ Service discovery: Find machines by name instead of IP address

✅ Multiple file transfer: Send multiple files in one go

✅ Directory transfer: Send entire folders with directory structure

✅ Progress indicator during transfer

✅ TCP socket-based transfer for reliability

## Windows GUI Version

A standalone **Windows GUI version** is also available as an **installable `.exe`**.

➡️ **Download the Windows GUI version**
*https://github.com/scorpionziky/file_transfer_app_0.1.3/releases/tag/0.1.4*

The Windows installer provides:

* Easy-to-use `.exe` setup
* Full GUI without requiring Python
* No external dependencies
* Compatible with Windows 10 and 11
* Complete interface for sending and receiving files or directories

> **Note:** The `.exe` version is built using PyInstaller.

## What's New in v0.1.4

Version 0.1.4 introduces several enterprise-grade features to enhance reliability and user control:

- **Pause/Resume Transfers** — Control transfer flow by pausing mid-stream and resuming without data loss. Ideal for managing bandwidth on constrained networks.
- **Automatic Retry Logic** — Failed transfers automatically retry up to 3 times with exponential backoff, eliminating manual intervention for transient network issues.
- **Optional ZIP Compression** — Enable compression before sending to reduce transfer time by 30-80% depending on file types.
- **Transfer History** — View detailed logs of past transfers (sent/received) with timestamps, file sizes, and transfer speeds for audit purposes.
- **File Received Notifications** — Optional system notifications when files arrive, allowing asynchronous monitoring.
- **Discovery IP Filtering** — Restrict discovery to specific subnets for enhanced security and network organization.
- **Automatic UI Recovery** — Built-in watchdog monitors UI responsiveness and automatically recovers from temporary freezes.

See [FEATURES_v0.1.4.md](FEATURES_v0.1.4.md) for detailed documentation on each feature.

## Requirements

Python 3.6 or higher (no additional packages required)

## Installation

* Clone or download this repository
* No additional installation required - uses only Python standard library

## Usage

### GUI Mode (Recommended)

For a user-friendly graphical interface:

```
python file_transfer_gui.py
```

The GUI provides:

#### Send File tab:

* Automatically discover machines on your network by name
* Or manually enter receiver's IP address
* Select multiple files to send together
* Or select folders to send with directory structure
* Real-time progress indicator
* View transfer log

#### Receive Files tab:

* Give your machine a friendly name for others to find
* Start/stop the receiver
* Choose output directory (files are auto-organized if from folders)
* See your IP address
* Real-time transfer logs
* Progress indicators
* Easy file and directory browsing

### Command-Line Mode

#### Receiving Files

On the computer that will receive the file, start the server:

```
python file_transfer.py receive --port 5000
```

Optional arguments:

* `--port`: Port to listen on (default: 5000)
* `--output-dir`: Directory to save received files (default: current directory)

Example with custom output directory:

```
python file_transfer.py receive --port 5000 --output-dir ./received_files
```

#### Sending Files

On the computer that will send the file:

```
python file_transfer.py send --host 192.168.1.100 --port 5000 --file document.pdf
```

Required arguments:

* `--host`: IP address or hostname of the receiving computer
* `--file`: Path to the file you want to send

Optional arguments:

* `--port`: Port of the receiver (default: 5000)

## How It Works

### Service Discovery

The application automatically discovers other machines on your network using UDP multicast/broadcast:

* When you open the GUI, it broadcasts a beacon announcing your machine name and receive port
* Other machines on the network also broadcast their beacons
* The list of machines updates in real-time as they are discovered
* If automatic discovery fails, you can manually enter IP addresses instead

Discovery operates on port **5007 (UDP)** — ensure your firewall allows outgoing and incoming UDP on this port.

### File Transfer Process

* The receiving computer starts a server that listens for incoming connections
* The sending computer connects to the server and transmits the file
* The transfer includes:

  * Filename
  * File size
  * File contents
  * Progress indicator
  * Acknowledgment upon completion

### Finding Your IP Address

**Windows**

```
ipconfig
```

Look for "IPv4 Address"

**Linux/macOS**

```
ip addr show    # Linux
ifconfig        # macOS/Linux
```

Look for "inet" address (usually 192.168.x.x or 10.x.x.x)

## Network Configuration

* Ensure both computers are on the same network
* Firewall may need to allow incoming connections on the chosen port
* For security reasons, this application is designed for trusted local networks only

## Security Notes

⚠️ **Important:** This tool is for trusted local networks only. It does **not** include:

* Encryption
* Authentication
* Authorization

Do **not** use over the internet or untrusted networks without additional security.

## Examples

### Example 1: Transfer a document

**Receiver (IP: 192.168.1.100):**

```
python file_transfer.py receive --port 5000
```

**Sender:**

```
python file_transfer.py send --host 192.168.1.100 --port 5000 --file report.pdf
```

### Example 2: Save files in a custom folder

**Receiver:**

```
python file_transfer.py receive --port 8080 --output-dir ~/Downloads/transfers
```

**Sender:**

```
python file_transfer.py send --host 192.168.1.100 --port 8080 --file vacation_photos.zip
```

## Troubleshooting

### Discovery Issues

If the GUI is not showing other machines:

#### Check your network

* Ensure all computers are on the same subnet
* Check IP ranges (e.g., 192.168.x.x)

#### Run the Discovery Diagnostic Tool

Use the GUI: **Help → Discovery Diagnostics**
Or run:

```
python test_network_discovery.py
```

#### Firewall Settings

* App uses UDP port 5007
* Windows Firewall: allow the app
* Windows network should be set to **Private**, not Public
* Some corporate networks block multicast — use Manual Connection

#### VPN / Virtual Networks

* VPNs may break discovery
* Use manual IP entry instead

### Other Issues

**Connection refused:**

* Ensure receiver is running
* Verify IP
* Check firewalls

**File not found:**

* Check file path
* Use absolute paths

**Permission denied:**

* Ensure read access to file
* Ensure write access to output directory

## License

This project is open source and available for personal and commercial use.

## Author

Created by: **Scorpionziky89**

For any issues, bugs, or questions, contact: **[scorpionziky89@gmail.com](mailto:scorpionziky89@gmail.com)**
