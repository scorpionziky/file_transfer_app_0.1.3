# Quick Start Guide

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

