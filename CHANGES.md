# Changes in Version 0.1.3

## Improvements Made

### 1. Service Discovery Enhancements ✅

**Problem**: Sometimes the application was not discovering other computers on the network.

**Solutions Implemented**:
- Dual-mode Broadcasting (multicast + UDP broadcast fallback)
- Faster beacon frequency (1 second instead of 2)
- Active UI polling for real-time updates
- Discovery Diagnostics menu for troubleshooting
- Command-line test tool for network testing

### 2. Multiple Files & Folder Transfer ✅

**Problem**: Application could only send single files, not multiple files or entire directories.

**Solutions Implemented**:

1. **Enhanced TransferClient** (`transfer_client.py`)
   - New method: `send_single_file()` - Send single file
   - New method: `send_multiple_files()` - Send multiple files in one transfer
   - New method: `send_directory()` - Send entire directory with structure preserved
   - Improved `send_file()` - Now auto-detects file vs directory
   - Combined progress tracking across all files

2. **Enhanced TransferServer** (`transfer_server.py`)
   - New method: `_receive_files()` - Handles both single and multiple files
   - New method: `_receive_single_file()` - Receives individual files
   - Automatic directory structure preservation
   - Fallback compatibility with old single-file protocol

3. **Improved GUI** (`file_transfer_gui.py`)
   - New file selection UI with listbox for multiple items
   - Buttons: "Add File(s)", "Add Folder", "Remove", "Clear All"
   - Dynamic file list display with sizes
   - Multi-file transfer progress tracking
   - Better logging for multi-file transfers

4. **Features**:
   - ✅ Select multiple files at once
   - ✅ Select folders to send with directory structure
   - ✅ Mix files and folders in single transfer
   - ✅ Progress bar shows total transfer progress
   - ✅ Log shows individual file progress
   - ✅ Received files preserve folder structure
   - ✅ Backward compatible with single-file transfers

## Previous Improvements

   - Added `_schedule_discovery_poll()` method
   - Updates the machine list every 1.5 seconds
   - No longer depends solely on callback triggers
   - More responsive UI updates
4. **Discovery Diagnostics** (`file_transfer_gui.py`)

   - New menu: **Help → Discovery Diagnostics**
   - Shows network status, local IP, and discovered peers
   - Tests multicast connectivity
   - Provides troubleshooting tips
   - Auto-runs diagnostics for quick feedback
5. **Improved Logging** (`file_transfer_gui.py`)

   - Better debug messages with [Discovery] tags
   - Shows which machines are broadcasting
   - Indicates when app is waiting for other machines
6. **Test Tool** (`test_network_discovery.py`)

   - New command-line utility for testing discovery
   - Shows which machines are visible on the network
   - Useful for network troubleshooting
   - Run: `python test_network_discovery.py`

### Documentation Updates

- **README.md**: Added "Service Discovery" section explaining how discovery works
- **README.md**: Added detailed "Troubleshooting" section for discovery issues
- **README.md**: Added instructions for using Discovery Diagnostic tool
- **CHANGES.md**: This file documenting all improvements

## Testing

Verified with simulation of multiple machines:

- ✅ 2-3 machines correctly discover each other
- ✅ Discovery updates in real-time
- ✅ Works with both multicast and broadcast
- ✅ Graceful handling of network issues

## Backward Compatibility

All changes are backward compatible. The application works the same from the user's perspective but with improved reliability.

## How to Use the New Features

### Discovery Diagnostics

1. Open the GUI application
2. Go to menu: **Help → Discovery Diagnostics**
3. Review the network status and peers found
4. Check tips if discovery isn't working

### Test Network Discovery

For advanced users or network troubleshooting:

```bash
python test_network_discovery.py
```

This tool shows real-time discovery of machines on your network.

### If Discovery Still Doesn't Work

1. **Check firewall** - Ensure UDP port 5007 is allowed
2. **Check network** - All computers must be on same network
3. **Manual Connection** - Use IP address directly if discovery fails
4. **Check for Windows "Public" network** - Change network to "Private" if possible

## Known Limitations

- Discovery requires at least 2 machines running the application on the same network
- Corporate firewalls may block multicast/broadcast (use Manual Connection)
- VPN connections may interfere with discovery (use Manual Connection)
- Different subnets won't see each other (network limitation)
