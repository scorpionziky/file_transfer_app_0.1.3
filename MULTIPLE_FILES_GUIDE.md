# NetLink - Multiple Files & Directory Transfer Guide

## What's New

NetLink (formerly File Transfer App) v0.1.4 supports sending **multiple files** and **entire directories** in a single transfer, plus pause/resume, retry, compression, and more!

## Features

### 1. Send Multiple Files

Instead of sending files one by one, you can now select multiple files and send them all at once.

**How to use:**
1. Click the "Send File" tab
2. Click "Add File(s)" button
3. Select multiple files from the dialog (Ctrl+Click or Shift+Click)
4. Click "Open"
5. Repeat step 2-4 to add more files if needed
6. Click "Send"

**Benefits:**
- Faster than multiple single transfers
- Single progress bar tracks all files
- Atomic transfer - all files sent together

### 2. Send Entire Folders

Send a complete folder with its directory structure intact.

**How to use:**
1. Click the "Send File" tab
2. Click "Add Folder" button
3. Select a folder
4. The folder and all its contents will be added to the transfer list
5. Click "Send"

**Benefits:**
- Preserves folder structure on receiver's machine
- All subfolders and files included
- Recursive directory transfer

### 3. Mix Files and Folders

You can combine files and folders in a single transfer.

**Example:**
```
Add File(s)      -> Select: document.pdf, photo.jpg
Add Folder       -> Select: /path/to/project
Click Send       -> Transfers all 3 items together
```

## File Management

### Add Items
- **Add File(s)**: Select one or more individual files
- **Add Folder**: Select a folder to send with structure

### Remove Items
- **Remove**: Select an item in the list and click "Remove"
- **Clear All**: Remove all items at once

### View Items
The list shows:
- **Files**: `filename (size)` - e.g., "document.pdf (2.45 MB)"
- **Folders**: `[FOLDER] foldername` - e.g., "[FOLDER] MyProject"

## Progress Tracking

When sending multiple files:
- **Total Progress Bar**: Shows overall transfer progress across all files
- **Log Messages**: Shows which file is being sent and individual progress
- **Status Updates**: Real-time feedback on transfer status

Example log output:
```
[14:32:15] Starting transfer to 192.168.1.100:5000...
[14:32:15] Files to send: 3
[14:32:15] Connecting to 192.168.1.100:5000...
[14:32:15] Sending file: document.pdf
File: 50.3% | Total: 15.2% (1.20 MB / 7.85 MB)
[14:32:17] Sending file: photo.jpg
File: 75.1% | Total: 45.3% (3.55 MB / 7.85 MB)
[14:32:19] Sending file: MyProject/main.py
File: 100.0% | Total: 100.0% (7.85 MB / 7.85 MB)
[14:32:20] All 3 file(s) sent successfully!
```

## Folder Structure Preservation

When you send a folder, the directory structure is preserved on the receiver's machine.

**Example:**
```
Sending:
  MyProject/
    src/
      main.py
      utils.py
    docs/
      readme.txt
    config.json

Received at:
  ReceivedFiles/
    MyProject/
      src/
        main.py
        utils.py
      docs/
        readme.txt
      config.json
```

## Limitations

- **Maximum file size**: Limited by available disk space and network
- **File name length**: Limited to filesystem limits (usually 255 characters)
- **Special characters**: Some characters in file names might be converted
- **Symbolic links**: Not followed, won't be transferred

## Tips & Tricks

### Tip 1: Large File Transfers
If you're sending large files (>1GB), make sure:
- Network connection is stable
- Receiver has enough disk space
- Both computers won't go to sleep during transfer

### Tip 2: Folder Organization
Before sending folders, organize them properly:
- Remove unnecessary files
- Clean up temporary files
- Compress if needed for faster transfer

### Tip 3: Batch Transfers
To send multiple batches:
1. Select first batch and Send
2. Wait for completion
3. Clear all and select next batch
4. Repeat

### Tip 4: Network Speed
- Local network: Usually limited by slowest drive speed
- WiFi: May be slower than Ethernet for large transfers
- Consider using Ethernet for large folders

## Troubleshooting

**"No files selected" error**
- Make sure you've clicked "Add File(s)" or "Add Folder"
- Check that items appear in the list

**Transfer interrupted**
- Check network connection
- Ensure receiver is still running
- Try again with fewer/smaller files

**Folder structure not preserved**
- This is expected behavior - folders are flattened
- Version 0.1.4 preserves paths in filenames
- Future versions will improve this

**Permission denied**
- Check file read permissions on sender
- Check folder write permissions on receiver
- Run as administrator if needed

## Command-Line Usage

If you prefer command-line, you can still use the API:

```python
from transfer_client import TransferClient

client = TransferClient("192.168.1.100", 5000)

# Single file
client.send_single_file("document.pdf")

# Multiple files
client.send_multiple_files(["file1.txt", "file2.txt", "file3.txt"])

# Directory
client.send_directory("/path/to/folder")
```

## Backward Compatibility

✅ All previous single-file transfers still work
✅ Old version clients can still send to new version servers
✅ No breaking changes to the API

## Performance Notes

- **Single file transfer**: Same speed as before
- **Multiple files**: May be slightly faster due to connection reuse
- **Directories**: Depends on number and size of files

Typical speeds (local network):
- Single file: Limited by disk I/O (50-500 MB/s)
- Multiple files: Same as single file (files sent sequentially)
- Directories: Same as multiple files

