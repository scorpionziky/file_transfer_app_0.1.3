# NetLink - Quick Start Guide

**NetLink** is a cross-platform file transfer application with automatic network discovery.

## Launch the GUI

```bash
python file_transfer_gui.py
```

## To Receive Files

1. Click the **"Receive Files"** tab
2. Give your machine a friendly name (default is your computer's hostname)
3. (Optional) Click **"Browse"** to choose where to save files
4. Click **"Start Receiver"**
5. Your machine will now be discoverable by others on the network
6. Wait for incoming files - they'll appear in the log when received

## To Send File(s) or Folder(s)

1. Click the **"Send Files"** tab
2. **Option A**: Select machines from the "Discovered Machines" list
   - **Option B**: Manually enter the receiver's IP address via "Advanced → Manual Connection"
3. **Add your files/folders**:
   - Click **"Add File(s)"** to select one or more files
   - Click **"Add Folder"** to select a folder (sent with directory structure)
   - Repeat to add multiple files/folders
   - Use "Remove" to remove selected items or "Clear All" to remove everything
4. Click **"Send"**
5. Watch the progress bar and log for transfer status

**Note**: Multiple files/folders are sent in a single transfer session for efficiency!

## Tips

- Both computers must be on the same network for discovery to work
- Machines appear in the list within 2-3 seconds of starting their receiver
- **Troubleshooting discovery?**
  - Go to **Help → Discovery Diagnostics** to check your network status
  - Or run: `python test_network_discovery.py`
  - If discovery fails, use the **Manual Connection** option to enter IP directly
- If a machine doesn't appear, you can still enter its IP address manually using **Advanced → Manual Connection**
- Use the default port (5000) unless it's already in use
- Keep the receiver running while sending files
- Check firewall settings if connection or discovery fails
- Firewall must allow UDP port 5007 for discovery to work

## Advanced Features

### Manual Connection (If Discovery Fails)

1. Click **Advanced → Manual Connection...**
2. Enter the IP address of the receiving computer
3. Enter the port (default 5000)
4. Proceed with file transfer

### Adjusting Preferences

1. Click **Settings → Preferences...**
2. Change machine name, port, or save folder
3. Discovery will automatically restart with new settings

## Enhanced Features in v0.1.4

**Transfer Control — Pause & Resume**

During an active transfer, you can pause to manage bandwidth or system resources, then resume seamlessly from where you left off. Simply click the pause button during transfer and click resume to continue.

**Performance — Data Compression**

Optional compression is available in the Advanced menu. When enabled, files are automatically compressed to ZIP format before transfer, typically reducing transfer time by 30-80% depending on file types (most effective for text files, source code, and documents).

**Monitoring — Transfer History**

Access your transfer history through Advanced → View Transfer History to review past transfers, including timestamps, file sizes, and transfer speeds. Useful for auditing and tracking transfer patterns.

**Notifications — File Received Alert**

Enable Advanced → Notify on file received to receive system notifications when files arrive, allowing you to monitor transfers without keeping the window in focus.

**Network Configuration — IP Filtering**

For enhanced security or network organization, use Advanced → Set Discovery IP Filter to restrict machine discovery to a specific subnet.

For comprehensive details on all v0.1.4 features, refer to [FEATURES_v0.1.4.md](FEATURES_v0.1.4.md).

