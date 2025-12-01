#!/usr/bin/env python3
"""
NetLink - Network File Transfer Application
Cross-platform graphical interface for file transfers
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import threading
import socket
import os
import time
import webbrowser
import sys
import json
import subprocess
import zipfile
from pathlib import Path
from transfer_server import TransferServer
from transfer_client import TransferClient
from service_discovery import ServiceDiscovery

# Application version
VERSION = "0.1.4"

# Optional drag-and-drop support via tkinterdnd2. If unavailable,
# the UI will continue to work without DnD.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    TKDND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    TKDND_AVAILABLE = False

# Optional system tray support using pystray + Pillow. If unavailable, feature is disabled.
try:
    import pystray
    from PIL import Image, ImageDraw

    TRAY_AVAILABLE = True
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
    TRAY_AVAILABLE = False
try:
    # Optional ImageTk for converting PIL images to Tk PhotoImage
    from PIL import ImageTk

    PIL_IMAGETK = True
except Exception:
    ImageTk = None
    PIL_IMAGETK = False


class FileTransferGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("NetLink")
        self.root.geometry("800x600")
        self.root.minsize(800, 600)  # Minimum window size
        self.root.resizable(True, True)
        
        # Configure modern font
        self.default_font = ("Segoe UI", 10)
        self.title_font = ("Segoe UI", 11, "bold")

        # Server thread reference/state
        self.server_thread = None
        self.server_running = False

        # Single service discovery instance for this machine
        self.discovery = None
        self._discovery_empty_logged = False
        # Track last incoming connection time (for monitoring firewall/connectivity issues)
        self.last_connection_time = None
        # Flag to avoid repeating the same warning
        self._no_conn_warned = False
        # After() id for scheduled connection checks
        self._connection_check_after_id = None
        # Server start timestamp for uptime checks
        self.server_start_time = None
        # Preference: whether discovery should use broadcast-only mode
        # Default: False => use multicast + broadcast
        self.broadcast_only_var = tk.BooleanVar(value=False)
        # Preference: whether to show detailed peer info in the discovered machines list
        self.show_peer_details = False

        # Selected files to send
        self.selected_files = []

        # Config file path (stored next to this script or in per-user folder)
        try:
            # If running as a frozen bundle (PyInstaller), avoid writing next to the
            # executable's temporary extract folder; use AppData/home instead.
            is_frozen = getattr(sys, 'frozen', False)
            candidate = Path(__file__).parent / "ft_gui_config.json"
            use_candidate = False

            try:
                import tempfile
                tempdir = tempfile.gettempdir()
            except Exception:
                tempdir = None

            # Determine whether candidate is acceptable (not running frozen and not inside tempdir)
            try:
                if not is_frozen:
                    if tempdir:
                        # skip candidate if it's inside the system temp directory
                        try:
                            if not str(candidate).startswith(str(tempdir)):
                                use_candidate = True
                        except Exception:
                            use_candidate = True
                    else:
                        use_candidate = True
            except Exception:
                use_candidate = False

            if use_candidate:
                try:
                    # test write permission by opening in append mode (won't truncate)
                    with open(candidate, 'a', encoding='utf-8'):
                        pass
                    self._config_path = candidate
                except Exception:
                    use_candidate = False

            if not use_candidate:
                # Fallback to per-user AppData (Windows) or home dir
                try:
                    appdata = os.getenv('APPDATA')
                    if appdata:
                        cfg_dir = Path(appdata) / "NetLink"
                    else:
                        cfg_dir = Path.home() / ".netlink"
                    cfg_dir.mkdir(parents=True, exist_ok=True)
                    self._config_path = cfg_dir / "ft_gui_config.json"
                except Exception:
                    # Last resort: current working directory
                    self._config_path = Path("ft_gui_config.json")
        except Exception:
            self._config_path = Path("ft_gui_config.json")

        # Logging file path
        try:
            self._log_file_path = Path(__file__).parent / "ft_gui_logs.txt"
        except Exception:
            self._log_file_path = Path("ft_gui_logs.txt")
        # Initialize log file
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"\n=== Session started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            pass

        # Load saved preferences (if any)
        try:
            self._load_config()
        except Exception:
            pass

        # Initialize preference variables BEFORE creating menu (menu uses these)
        # Notification preference (beep on new file received)
        self.notify_on_receive = True
        
        # Discovery filter: optional IP subnet filter (e.g., '192.168.1.')
        self.discovery_ip_filter = None  # None = no filter (accept all)
        
        # Compression preference
        self.compress_before_send = False

        # Transfer control: pause/resume state
        self.transfer_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Initially not paused

        # Transfer history (for display in Advanced menu)
        try:
            self._history_path = Path(__file__).parent / "ft_transfer_history.json"
        except Exception:
            self._history_path = Path("ft_transfer_history.json")
        self.transfer_history = []  # List of {'type': 'send'|'recv', 'filename', 'size', 'timestamp', 'duration_sec'}
        self._load_transfer_history()

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        # Create tabs
        self.send_frame = ttk.Frame(self.notebook)
        self.receive_frame = ttk.Frame(self.notebook)
        self.about_frame = ttk.Frame(self.notebook)
        self.magi_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.send_frame, text="📤 Send Files")
        self.notebook.add(self.receive_frame, text="📥 Receive Files")
        self.notebook.add(self.about_frame, text="ℹ️ About")

        self._create_send_tab()
        self._create_receive_tab()
        self._create_magi_tab()
        self._create_about_tab()

        # Status bar at bottom
        self.status_bar = ttk.Label(root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Create menu bar
        self._create_menu_bar()

        # Initialize tray icon if available
        try:
            if TRAY_AVAILABLE:
                self._init_tray()
        except Exception:
            pass

        # Polling timer for periodic discovery updates
        self.last_peers = {}
        # Maintain current ordered list of peer names shown in the listbox
        self._machines_order = []
        # Cache for small status images to show colored dots in Treeview
        self._status_images = {}
        # Keep references to images used by Treeview items to avoid GC
        self._item_images = {}

        # Health check: monitor for blocked/stuck threads after standby
        self._health_check_counter = 0
        self._last_poll_time = time.time()

        # UI timeout watchdog: detect frozen GUI and refresh/recover
        self._ui_last_response_time = time.time()
        self._ui_timeout_threshold = 5  # seconds; if no response in 5s, consider frozen
        self._ui_frozen_recovered = False  # flag to prevent repeated recovery attempts

        # Start discovery after UI is ready
        self.root.after(1000, self.start_discovery_service)

        # Start periodic polling to update machines list (every 1.5 seconds)
        self._schedule_discovery_poll()

        # Start health check monitor (every 30 seconds)
        self._schedule_health_check()

        # Start UI watchdog (every 2 seconds) to detect frozen GUI
        self._schedule_ui_watchdog()

        # Easter-egg: beta badge click counter and NERV mode state
        self._beta_click_count = 0
        self._nerv_mode = False
        # store original root bg so we can restore later
        try:
            self._original_root_bg = self.root.cget('bg')
        except Exception:
            self._original_root_bg = None

    # -------------------------
    # Discovery helpers
    # -------------------------
    def _schedule_discovery_poll(self):
        """Schedule periodic discovery list updates"""
        try:
            if self.discovery:
                current_peers = self.discovery.get_peers()
                # Update list if peers changed
                if current_peers != self.last_peers:
                    self.last_peers = current_peers
                    self._update_machines_list()
            # Mark that poll succeeded
            self._last_poll_time = time.time()
        except Exception:
            pass

        # Schedule next poll
        self.root.after(1500, self._schedule_discovery_poll)

    def _schedule_health_check(self):
        """Schedule periodic health checks to detect and recover from standby-induced freezes."""
        try:
            self._health_check()
        except Exception:
            pass

        # Schedule next health check (every 30 seconds)
        self.root.after(30000, self._schedule_health_check)

    def _schedule_ui_watchdog(self):
        """Schedule periodic UI responsiveness checks."""
        try:
            self._ui_watchdog()
        except Exception:
            pass

        # Schedule next UI watchdog check (every 2 seconds)
        self.root.after(2000, self._schedule_ui_watchdog)

    def _get_status_image(self, color_hex: str, size: int = 12):
        """Return a small circular PhotoImage of the given color.

        Uses PIL Image if available (better rendering). Falls back to None
        so callers can use a unicode emoji when PIL is not present.
        """
        try:
            # reuse cached image if exists
            key = f"{color_hex}_{size}"
            img = self._status_images.get(key)
            if img:
                return img

            if PIL_IMAGETK and Image is not None and ImageDraw is not None and ImageTk is not None:
                im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                draw = ImageDraw.Draw(im)
                draw.ellipse((1, 1, size - 2, size - 2), fill=color_hex)
                pimg = ImageTk.PhotoImage(im)
                # cache and return
                self._status_images[key] = pimg
                return pimg
            # If PIL not available, return None and let caller use emoji fallback
            return None
        except Exception:
            return None

    def _ui_watchdog(self):
        """Monitor GUI responsiveness; log warning if UI frozen."""
        now = time.time()
        time_since_response = now - self._ui_last_response_time
        
        if time_since_response > self._ui_timeout_threshold:
            if not self._ui_frozen_recovered:
                try:
                    self._log_receive(f"[UI Timeout] GUI unresponsive for {time_since_response:.1f}s; attempting recovery...")
                except Exception:
                    pass
                
                # Attempt recovery: refresh discovery and UI
                try:
                    self._ui_frozen_recovered = True
                    # Force a discovery refresh by calling update_machines_list
                    self._update_machines_list()
                except Exception:
                    pass
                
                try:
                    self._log_receive("[UI Timeout] UI recovery attempted")
                except Exception:
                    pass
        else:
            # UI is responsive; reset recovery flag
            self._ui_frozen_recovered = False
        
        # Update last response time (called by main loop)
        self._ui_last_response_time = now

    def _health_check(self):
        """Check if discovery is responsive; restart if stuck (common after PC standby)."""
        try:
            now = time.time()
            # If the last poll happened more than 60 seconds ago, discovery may be stuck
            time_since_poll = now - self._last_poll_time
            
            if time_since_poll > 60:
                # Discovery appears stuck; try to recover
                try:
                    self._log_receive(f"[Health Check] Discovery unresponsive ({time_since_poll:.0f}s); attempting recovery...")
                except Exception:
                    pass
                
                # Stop and restart discovery
                try:
                    if self.discovery:
                        try:
                            self.discovery.stop()
                        except Exception:
                            pass
                        self.discovery = None
                except Exception:
                    pass
                
                # Restart discovery
                try:
                    machine_name = socket.gethostname()
                    try:
                        port = int(self.receive_port_entry.get().strip())
                    except Exception:
                        port = 5000
                    self._start_discovery(machine_name, port)
                    self._log_receive("[Health Check] Discovery restarted successfully")
                except Exception as e:
                    self._log_receive(f"[Health Check] Failed to restart discovery: {e}")
        except Exception:
            pass

    def _start_discovery(self, machine_name: str, port: int):
        """Create and start a ServiceDiscovery instance for this machine."""
        try:
            # If already running, stop it first
            if self.discovery:
                try:
                    self.discovery.stop()
                except Exception:
                    pass
                self.discovery = None

            # Create discovery (broadcast=True so EVERY machine announces itself)
            self.discovery = ServiceDiscovery(
                machine_name,
                port,
                callback=lambda: self.root.after(0, self._update_machines_list),
                broadcast=True,
                broadcast_only=self.broadcast_only_var.get(),
            )
            self.discovery.start()
            # Indicate mode in GUI and logs
            mode = (
                "broadcast-only"
                if getattr(self.discovery, "broadcast_only", False)
                else "multicast+broadcast"
            )
            try:
                self.discovery_mode_var.set(f"Discovery: {mode}")
            except Exception:
                pass
            # keep send tab indicator in sync if present
            try:
                if hasattr(self, 'send_discovery_var'):
                    self.send_discovery_var.set(f"Discovery: {mode}")
                    # color-code: broadcast-only -> red/orange, otherwise green
                    # Keep discovery indicator consistently blue regardless of mode
                    try:
                        self.send_discovery_label.config(foreground='blue')
                    except Exception:
                        pass
            except Exception:
                pass
            self._log_receive(f"[Discovery] Mode: {mode}")
            self._log_send(
                f"[Discovery] Broadcasting '{machine_name}' on port {port} (mode: {mode})"
            )
            self._log_send(f"[Discovery] Listening for other machines...")
        except Exception as e:
            self._log_send(f"[Discovery ERROR] {e}")

    def _on_broadcast_toggle(self):
        """Handler called when user toggles the 'Broadcast-only' checkbox in the UI.

        Restarts the discovery service with the new setting so changes take effect immediately.
        """
        try:
            # Determine port to use
            try:
                port = int(self.receive_port_entry.get().strip())
            except Exception:
                port = 5000

            machine_name = socket.gethostname()

            # If discovery running, stop and restart with new mode
            try:
                if self.discovery:
                    self.discovery.stop()
            except Exception:
                pass
            self.discovery = None

            self._start_discovery(machine_name, port)
            self._log_receive(
                f"[Discovery] Broadcast-only set to {self.broadcast_only_var.get()}"
            )
            # Persist the new setting
            try:
                self._write_config()
            except Exception:
                pass
            # Update send tab indicator color/text
            try:
                mode = (
                    "broadcast-only" if self.broadcast_only_var.get() else "multicast+broadcast"
                )
                if hasattr(self, 'send_discovery_var'):
                    self.send_discovery_var.set(f"Discovery: {mode}")
                    try:
                        self.send_discovery_label.config(foreground='blue')
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            self._log_receive(f"[Discovery ERROR] {e}")

    def start_discovery_service(self):
        """Start the single discovery service using a consistent machine name."""
        try:
            machine_name = socket.gethostname()  # nome unico e coerente
            # If the server is not listening, use a fallback discovery port
            # This allows the machine to be discovered even if it's not currently receiving files
            try:
                receive_port = int(self.receive_port_entry.get().strip())
            except Exception:
                receive_port = 5000

            # ALWAYS broadcast the beacon, regardless of server running state
            self._start_discovery(machine_name, receive_port)
        except Exception as e:
            self._log_send(f"[Discovery ERROR] {e}")

    # -------------------------
    # UI: menu, tabs, etc.
    # -------------------------

    def _create_menu_bar(self):
        """Create the menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Advanced menu
        advanced_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Advanced", menu=advanced_menu)
        advanced_menu.add_command(
            label="Manual Connection...", command=self._open_manual_connection_dialog
        )
        advanced_menu.add_separator()
        advanced_menu.add_command(
            label="Transfer History", command=self._view_transfer_history
        )
        advanced_menu.add_command(
            label="Export Transfer History...", command=self._export_transfer_history_csv
        )
        advanced_menu.add_command(
            label="Clear Transfer History", command=self._clear_transfer_history
        )
        advanced_menu.add_separator()
        advanced_menu.add_command(
            label="Discovery IP Filter...", command=self._open_discovery_filter_dialog
        )
        advanced_menu.add_checkbutton(
            label="Notify on file received (beep)", variable=tk.BooleanVar(value=self.notify_on_receive),
            command=lambda: setattr(self, 'notify_on_receive', not self.notify_on_receive)
        )
        advanced_menu.add_checkbutton(
            label="Compress before send (ZIP)", variable=tk.BooleanVar(value=self.compress_before_send),
            command=lambda: setattr(self, 'compress_before_send', not self.compress_before_send)
        )

        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(
            label="Preferences...", command=self._open_preferences_dialog
        )
        settings_menu.add_command(
            label="Reset Preferences", command=self._reset_preferences
        )
        settings_menu.add_separator()
        settings_menu.add_command(
            label="Clean Partial Files...", command=self._cleanup_partial_files_dialog
        )

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(
            label="Discovery Diagnostics", command=self._run_diagnostics
        )
        help_menu.add_command(label="Quick Guide (IT)", command=self._open_quick_guide)
        help_menu.add_command(
            label="Quick Guide (EN)", command=self._open_quick_guide_en
        )
        help_menu.add_separator()
        help_menu.add_command(label="Save Logs", command=self._send_logs)

    def _run_diagnostics(self):
        """Run discovery diagnostics"""
        diagnostics_window = tk.Toplevel(self.root)
        diagnostics_window.title("Discovery Diagnostics")
        diagnostics_window.geometry("500x400")
        diagnostics_window.transient(self.root)

        # Title
        title_label = ttk.Label(
            diagnostics_window, text="Discovery Diagnostics", font=("Arial", 12, "bold")
        )
        title_label.pack(pady=10)

        # Text area for output
        output_text = scrolledtext.ScrolledText(
            diagnostics_window, height=20, state="disabled", font=("Courier", 9)
        )
        output_text.pack(fill="both", expand=True, padx=10, pady=10)

        def log_diag(message):
            output_text.config(state="normal")
            timestamp = time.strftime("%H:%M:%S")
            output_text.insert(tk.END, f"[{timestamp}] {message}\n")
            output_text.see(tk.END)
            output_text.config(state="disabled")
            output_text.update()

        def run_tests():
            log_diag("[INFO] Starting discovery diagnostics...\n")

            # Test 1: Network info
            log_diag(f"Machine: {socket.gethostname()}")
            log_diag(f"Local IP: {self._get_local_ip()}")

            # Test 2: Discovery status
            log_diag(f"\nDiscovery Status:")
            if self.discovery:
                log_diag(f"  - Running: Yes")
                peers = self.discovery.get_peers()
                log_diag(f"  - Peers found: {len(peers)}")
                for name, info in peers.items():
                    log_diag(f"    * {name}: {info['ip']}:{info['port']}")
            else:
                log_diag(f"  - Running: No")

            # Test 3: Port info
            log_diag(f"\nConfiguration:")
            try:
                recv_port = int(self.receive_port_entry.get().strip())
                log_diag(f"  - Receive port: {recv_port}")
            except:
                log_diag(f"  - Receive port: Invalid")

            log_diag(f"  - Server running: {'Yes' if self.server_running else 'No'}")

            # Test 4: Network connectivity
            log_diag(f"\nNetwork Tests:")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", 5007))

                import struct

                mreq = struct.pack(
                    "4sl", socket.inet_aton("239.255.77.77"), socket.INADDR_ANY
                )
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                log_diag(f"  - Multicast: OK")
                s.close()
            except Exception as e:
                log_diag(f"  - Multicast: FAILED ({e})")

            log_diag(f"\nTips:")
            log_diag(f"1. Make sure at least 2 computers are running this app")
            log_diag(f"2. All machines must be on the same network")
            log_diag(f"3. Firewall may block UDP port 5007")
            log_diag(f"4. Use Manual Connection if Discovery doesn't work")
            log_diag(f"\n[OK] Diagnostics complete")

        # Run button
        btn_frame = ttk.Frame(diagnostics_window)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Run Diagnostics", command=run_tests).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="Close", command=diagnostics_window.destroy).pack(
            side=tk.LEFT, padx=5
        )

        # Auto-run tests
        # Ensure dialog visible and then auto-run tests
        try:
            self._ensure_dialog_visible(diagnostics_window)
        except Exception:
            pass
        self.root.after(100, run_tests)

    def _open_quick_guide(self):
        """Open a small Quick Guide and Troubleshooting help window (Italian)."""
        guide = tk.Toplevel(self.root)
        guide.title("Quick Guide & Troubleshooting")
        guide.geometry("600x500")
        guide.transient(self.root)

        text = scrolledtext.ScrolledText(
            guide, wrap=tk.WORD, state="normal", font=("Arial", 10)
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)

        guide_content = (
            "Breve guida al programma\n"
            "-----------------------\n\n"
            "Come funziona (sintesi):\n"
            "- Questo programma usa UDP (multicast/broadcast) per scoprire altri computer in rete.\n"
            "- Usa TCP per il trasferimento affidabile dei file.\n"
            "- Puoi avviare il ricevitore (Start Receiver) su una macchina e inviare file da un'altra.\n\n"
            "Passi rapidi per inviare/ricevere file:\n"
            "1) Su chi riceve: apri la tab 'Receive Files' -> imposta la cartella e clicca 'Start Receiver'.\n"
            "2) Su chi invia: seleziona il destinatario dalla lista 'Discovered Machines' o usa 'Manual Connection...'.\n"
            "3) Aggiungi File o Cartelle nella tab 'Send Files' e premi 'Send'.\n\n"
            "Problemi comuni e risoluzioni rapide:\n"
            "- Non vedo altri computer nella lista: controlla che tutte le macchine siano nella stessa rete e che il firewall non blocchi UDP 5007. Usa 'Discovery Diagnostics' per verificare.\n"
            "- Il file non arriva: assicurati che il ricevitore abbia premuto 'Start Receiver' e che la porta mostrata sia raggiungibile (default 5000). Prova la 'Manual Connection' inserendo l'IP del ricevente.\n"
            "- Ricevo l'avviso 'No incoming connections': il programma mostra un indicatore arancione se il server ascolta ma non riceve connessioni; spesso è un firewall o la porta non è inoltrata. Apri le impostazioni di rete o disattiva temporaneamente il firewall per test.\n\n"
            "Suggerimenti avanzati:\n"
            "- Se la scoperta non funziona, usa sempre 'Manual Connection' con IP e porta.\n"
            "- Per trasferimenti multipli grandi, verifica spazio su disco nella cartella di destinazione.\n"
            "- Usa i log nelle tabs 'Transfer Log' e 'Receiver Log' per vedere messaggi di errore e diagnostica.\n\n"
            "Se hai bisogno di aiuto avanzato, invia i messaggi dei log (dal menu) o apri un issue su GitHub con dettagli di rete e gli output della 'Discovery Diagnostics'.\n"
        )

        text.insert(tk.END, guide_content)
        text.config(state="disabled")
        try:
            self._ensure_dialog_visible(guide)
        except Exception:
            pass

    def _ensure_txt_docs(self):
        """Create .txt copies of documentation .md files if .txt not present.

        This makes it easier for the app to open plain-text files on demand.
        """
        try:
            base = Path(__file__).parent
        except Exception:
            return

        pairs = [
            ("QUICK_START.md", "QUICK_START.txt"),
            ("README.md", "README.txt"),
        ]

        for md_name, txt_name in pairs:
            try:
                md_path = base / md_name
                txt_path = base / txt_name
                if md_path.exists() and not txt_path.exists():
                    try:
                        with open(md_path, 'r', encoding='utf-8') as rf:
                            content = rf.read()
                        # Write raw markdown to .txt (preserve readable content)
                        with open(txt_path, 'w', encoding='utf-8') as wf:
                            wf.write(content)
                    except Exception:
                        # If writing fails, skip silently
                        pass
            except Exception:
                pass

    def _refresh_docs_txt(self):
        """Regenerate .txt documentation files and notify the user."""
        try:
            self._ensure_txt_docs()
            messagebox.showinfo("Refresh Docs TXT", "Documentation .txt files refreshed (if .md present).")
            self._log_send("Documentation .txt refreshed by user")
        except Exception as e:
            try:
                messagebox.showerror("Refresh Error", f"Could not refresh docs: {e}")
            except Exception:
                pass

    def _open_quick_guide_en(self):
        """Open a small Quick Guide and Troubleshooting help window (English)."""
        guide = tk.Toplevel(self.root)
        guide.title("Quick Guide & Troubleshooting")
        guide.geometry("600x500")
        guide.transient(self.root)

        text = scrolledtext.ScrolledText(
            guide, wrap=tk.WORD, state="normal", font=("Arial", 10)
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)

        guide_content = (
            "Quick Guide\n"
            "-----------------------\n\n"
            "How it works (summary):\n"
            "- This app uses UDP (multicast/broadcast) to discover other computers on the local network.\n"
            "- It uses TCP for reliable file transfers.\n"
            "- Start the receiver on one machine and send files from another.\n\n"
            "Quick steps to send/receive files:\n"
            "1) On the receiver: open 'Receive Files' -> set the folder and click 'Start Receiver'.\n"
            "2) On the sender: select the receiver from 'Discovered Machines' or use 'Manual Connection...'.\n"
            "3) Add Files or Folders in the 'Send Files' tab and click 'Send'.\n\n"
            "Common problems and quick fixes:\n"
            "- No machines in the list: ensure all computers are on the same network and that UDP port 5007 is not blocked by firewall. Use 'Discovery Diagnostics' to check.\n"
            "- File doesn't arrive: ensure the receiver pressed 'Start Receiver' and the port (default 5000) is reachable. Try 'Manual Connection' with the receiver IP.\n"
            "- 'No incoming connections' warning: the app shows an orange indicator if the server listens but receives no connections; this often indicates a firewall or network configuration blocking the port. Check firewall settings or allow the app through the firewall for testing.\n\n"
            "Advanced tips:\n"
            "- If discovery fails, always try 'Manual Connection' with IP and port.\n"
            "- For large transfers, verify available disk space on the destination folder.\n"
            "- Check 'Transfer Log' and 'Receiver Log' for detailed messages and errors.\n\n"
            "If you need more help, collect the logs and diagnostics output and open an issue on GitHub including network details and the diagnostics output.\n"
        )

        text.insert(tk.END, guide_content)
        text.config(state="disabled")
        try:
            self._ensure_dialog_visible(guide)
        except Exception:
            pass

    def _send_logs(self):
        """Collect GUI logs and let the user save them (Save As), open the saved file and copy path to clipboard."""
        try:
            # Collect logs (if widgets exist)
            try:
                send_text = self.send_log.get("1.0", tk.END)
            except Exception:
                send_text = ""
            try:
                recv_text = self.receive_log.get("1.0", tk.END)
            except Exception:
                recv_text = ""

            # Default filename
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            default_name = f"ft_logs_{timestamp}.txt"

            # Ask user where to save the logs
            save_path = filedialog.asksaveasfilename(
                title="Save Logs As",
                defaultextension=".txt",
                initialfile=default_name,
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            )
            if not save_path:
                return  # user cancelled

            out_path = Path(save_path)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(
                    f"File Transfer App Logs - {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )
                f.write("--- SEND LOG ---\n")
                f.write(send_text or "(empty)\n")
                f.write("\n--- RECEIVE LOG ---\n")
                f.write(recv_text or "(empty)\n")

            # Open the saved file for the user
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(out_path))
                else:
                    import subprocess

                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.Popen([opener, str(out_path)])
            except Exception:
                pass

            # Copy path to clipboard for easy pasting
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(str(out_path))
            except Exception:
                pass

            messagebox.showinfo(
                "Logs Saved", f"Logs saved to:\n{out_path}\n\nPath copied to clipboard."
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not prepare logs: {e}")

    # -------------------------
    # System tray helpers
    # -------------------------
    def _create_tray_image(self, size=64, color=(52, 152, 219)):
        """Create a simple circular tray icon (Pillow Image)."""
        if not TRAY_AVAILABLE or Image is None or ImageDraw is None:
            return None
        try:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # draw a filled circle
            margin = int(size * 0.12)
            draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
            return img
        except Exception:
            return None

    def _init_tray(self):
        """Initialize and run the system tray icon in a background thread."""
        if not TRAY_AVAILABLE or pystray is None:
            return

        def _on_show(icon, item):
            try:
                self.root.after(0, self._show_from_tray)
            except Exception:
                pass

        def _on_hide(icon, item):
            try:
                self.root.after(0, self._hide_to_tray)
            except Exception:
                pass

        def _on_start(icon, item):
            try:
                self.root.after(0, self._start_server)
            except Exception:
                pass

        def _on_stop(icon, item):
            try:
                self.root.after(0, self._stop_server)
            except Exception:
                pass

        def _on_exit(icon, item):
            try:
                # stop tray icon then close app
                icon.stop()
            except Exception:
                pass
            try:
                # perform cleanup and destroy root
                self._cleanup_and_exit()
            except Exception:
                try:
                    self.root.destroy()
                except Exception:
                    pass

        image = self._create_tray_image()
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show", _on_show),
                pystray.MenuItem("Hide", _on_hide),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start Receiver", _on_start),
                pystray.MenuItem("Stop Receiver", _on_stop),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", _on_exit),
            )

            self._tray_icon = pystray.Icon(
                "file_transfer_app", image, "File Transfer", menu
            )

            t = threading.Thread(target=self._tray_icon.run, daemon=True)
            t.start()
        except Exception:
            self._tray_icon = None

    def _hide_to_tray(self):
        try:
            # Persist preferences before hiding to tray so settings remain after closing
            try:
                self._write_config()
            except Exception:
                pass
            self.root.withdraw()
            self._log_send("Application hidden to tray")
        except Exception:
            pass

    def _show_from_tray(self):
        try:
            self.root.deiconify()
            try:
                self.root.lift()
            except Exception:
                pass
            self._log_send("Application restored from tray")
        except Exception:
            pass

    def _load_transfer_history(self):
        """Load transfer history from JSON file."""
        try:
            if self._history_path.exists():
                with open(self._history_path, 'r', encoding='utf-8') as f:
                    self.transfer_history = json.load(f)
        except Exception:
            self.transfer_history = []

    def _save_transfer_history(self):
        """Save transfer history to JSON file."""
        try:
            with open(self._history_path, 'w', encoding='utf-8') as f:
                json.dump(self.transfer_history[-100:], f, indent=2)  # Keep last 100 entries
        except Exception:
            pass

    def _add_transfer_history(self, transfer_type, filename, size_bytes, duration_sec):
        """Add entry to transfer history (type: 'send' or 'recv')."""
        try:
            entry = {
                'type': transfer_type,
                'filename': filename,
                'size_bytes': size_bytes,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'duration_sec': duration_sec,
                'speed_mbps': (size_bytes / (1024 * 1024)) / max(0.1, duration_sec)
            }
            self.transfer_history.append(entry)
            self._save_transfer_history()
        except Exception:
            pass

    def _notify_file_received(self, filename):
        """Notify user of new received file (beep + visual)."""
        try:
            if self.notify_on_receive:
                # Beep (platform-agnostic using tkinter)
                try:
                    self.root.bell()
                except Exception:
                    pass
        except Exception:
            pass

    def _view_transfer_history(self):
        """Show transfer history dialog."""
        try:
            hist_win = tk.Toplevel(self.root)
            hist_win.title("Transfer History")
            hist_win.geometry("700x400")
            hist_win.transient(self.root)

            # Text widget with scrollbar
            text = scrolledtext.ScrolledText(hist_win, height=20, state="disabled", font=("Courier", 9))
            text.pack(fill="both", expand=True, padx=10, pady=10)

            # Format history
            text.config(state="normal")
            if not self.transfer_history:
                text.insert(tk.END, "No transfers recorded yet.\n")
            else:
                text.insert(tk.END, f"{'Type':<6} {'Timestamp':<20} {'Filename':<30} {'Size':<10} {'Duration':<10} {'Speed':<10}\n")
                text.insert(tk.END, "-" * 100 + "\n")
                for entry in self.transfer_history[-50:]:  # Show last 50
                    ttype = entry.get('type', 'unk')
                    ts = entry.get('timestamp', '')
                    fname = entry.get('filename', '')[:30]
                    size = f"{entry.get('size_bytes', 0) / (1024*1024):.1f}MB"
                    dur = f"{entry.get('duration_sec', 0):.1f}s"
                    spd = f"{entry.get('speed_mbps', 0):.2f}MB/s"
                    text.insert(tk.END, f"{ttype:<6} {ts:<20} {fname:<30} {size:<10} {dur:<10} {spd:<10}\n")
            text.config(state="disabled")

            # Close button
            ttk.Button(hist_win, text="Close", command=hist_win.destroy).pack(pady=10)
            self._ensure_dialog_visible(hist_win)
        except Exception as e:
            messagebox.showerror("Error", f"Could not display history: {e}")

    def _export_transfer_history_csv(self):
        """Export current transfer history to CSV file chosen by user."""
        try:
            if not self.transfer_history:
                messagebox.showinfo("Export Transfer History", "No transfer history to export.")
                return
            path = filedialog.asksaveasfilename(
                title="Export Transfer History",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*")],
            )
            if not path:
                return
            # Write CSV
            import csv

            with open(path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["type", "filename", "size_bytes", "timestamp", "duration_sec", "speed_mbps"])
                for entry in self.transfer_history:
                    writer.writerow([
                        entry.get('type', ''),
                        entry.get('filename', ''),
                        entry.get('size_bytes', 0),
                        entry.get('timestamp', ''),
                        entry.get('duration_sec', 0),
                        entry.get('speed_mbps', 0),
                    ])
            messagebox.showinfo("Export Transfer History", f"Exported {len(self.transfer_history)} entries to {path}")
            self._log_send(f"Exported transfer history to {path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not export history: {e}")

    def _clear_transfer_history(self):
        """Clear stored transfer history after confirmation."""
        try:
            if not messagebox.askyesno("Clear Transfer History", "Are you sure you want to clear the stored transfer history? This cannot be undone."):
                return
            self.transfer_history = []
            try:
                if self._history_path.exists():
                    try:
                        self._history_path.unlink()
                    except Exception:
                        # fallback: overwrite
                        self._save_transfer_history()
                else:
                    self._save_transfer_history()
            except Exception:
                pass
            self._log_send("Transfer history cleared by user")
            messagebox.showinfo("Clear Transfer History", "Transfer history cleared.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not clear history: {e}")

    def _cleanup_and_exit(self):
        """Stop services and exit the application cleanly."""
        try:
            if self.server_running:
                try:
                    self._stop_server()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self.discovery:
                try:
                    self.discovery.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._write_config()
        except Exception:
            pass
        try:
            self._save_transfer_history()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _reset_preferences(self):
        """Reset preferences to defaults after user confirmation."""
        try:
            if not messagebox.askyesno(
                "Reset Preferences",
                "Reset preferences to defaults? This will overwrite saved settings.",
            ):
                return

            # Defaults
            default_port = "5000"
            default_output = os.path.join(os.getcwd(), "ReceivedFiles")
            default_name = socket.gethostname()

            # Reset UI fields
            try:
                self.receive_port_entry.config(state="normal")
                self.receive_port_entry.delete(0, tk.END)
                self.receive_port_entry.insert(0, default_port)
            except Exception:
                pass

            try:
                self.machine_name_entry.config(state="normal")
                self.machine_name_entry.delete(0, tk.END)
                self.machine_name_entry.insert(0, default_name)
            except Exception:
                pass

            try:
                self.output_dir_var.set(default_output)
            except Exception:
                pass

            # Reset broadcast-only preference (default: multicast + broadcast)
            try:
                self.broadcast_only_var.set(False)
            except Exception:
                pass
            # Reset partial cleanup preference
            try:
                self.partial_cleanup_days = 30
                self.auto_cleanup_partial = False
            except Exception:
                pass

            # Persist defaults
            try:
                self._write_config()
            except Exception:
                pass

            # Restart discovery with defaults
            try:
                # Stop existing discovery
                if self.discovery:
                    try:
                        self.discovery.stop()
                    except Exception:
                        pass
                    self.discovery = None

                self._start_discovery(default_name, int(default_port))
                self._log_receive("Preferences reset to defaults")
            except Exception as e:
                self._log_receive(f"Error restarting discovery: {e}")

        except Exception as e:
            messagebox.showerror("Error", f"Could not reset preferences: {e}")

    def _open_manual_connection_dialog(self):
        """Dialog for manual IP/port configuration"""
        current_host = self.host_entry.get().strip()
        current_port = self.send_port_entry.get().strip() or "5000"

        host = simpledialog.askstring(
            "Manual Connection", "Receiver IP Address:", initialvalue=current_host or ""
        )
        if host is None or not host.strip():
            return

        port_str = simpledialog.askstring(
            "Manual Connection", "Port:", initialvalue=current_port
        )
        if port_str is None:
            return

        try:
            int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number.")
            return

        self.host_entry.delete(0, tk.END)
        self.host_entry.insert(0, host.strip())
        self.send_port_entry.delete(0, tk.END)
        self.send_port_entry.insert(0, port_str.strip())

    def _open_discovery_filter_dialog(self):
        """Dialog to set optional IP subnet filter for discovery."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Discovery IP Filter")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("300x150")

        ttk.Label(dialog, text="Filter discovery by IP subnet (optional):").pack(padx=10, pady=10)
        ttk.Label(dialog, text="Examples: 192.168.1., 10.0., or leave empty for no filter", font=("Arial", 8)).pack(padx=10)

        frame = ttk.Frame(dialog)
        frame.pack(padx=10, pady=10, fill="x")
        ttk.Label(frame, text="IP Prefix:").pack(side=tk.LEFT)
        filter_var = tk.StringVar(value=self.discovery_ip_filter or "")
        entry = ttk.Entry(frame, textvariable=filter_var, width=20)
        entry.pack(side=tk.LEFT, padx=5)

        def save_filter():
            val = filter_var.get().strip()
            self.discovery_ip_filter = val if val else None
            messagebox.showinfo("Filter Set", f"Discovery filter: {val if val else 'None (accept all)'}")
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save_filter).pack(pady=10)
        self._ensure_dialog_visible(dialog)

    def _open_preferences_dialog(self):
        """Preferences dialog for machine name, folder, default ports"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Preferences")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("400x200")

        # Machine name
        frame_name = ttk.Frame(dialog)
        frame_name.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_name, text="Machine Name:").pack(side=tk.LEFT)
        name_var = tk.StringVar(value=self.machine_name_entry.get())
        name_entry = ttk.Entry(frame_name, textvariable=name_var, width=25)
        name_entry.pack(side=tk.LEFT, padx=5)

        # Receive port
        frame_port = ttk.Frame(dialog)
        frame_port.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_port, text="Receive Port (default):").pack(side=tk.LEFT)
        recv_port_var = tk.StringVar(value=self.receive_port_entry.get())
        recv_port_entry = ttk.Entry(frame_port, textvariable=recv_port_var, width=8)
        recv_port_entry.pack(side=tk.LEFT, padx=5)

        # Discovery options
        frame_discovery = ttk.Frame(dialog)
        frame_discovery.pack(fill="x", padx=10, pady=5)
        discover_chk_var = tk.BooleanVar(value=self.broadcast_only_var.get())
        discover_chk = ttk.Checkbutton(
            frame_discovery, text="Broadcast-only discovery", variable=discover_chk_var
        )
        discover_chk.pack(side=tk.LEFT)

        # Show peer details option
        details_chk_var = tk.BooleanVar(value=getattr(self, "show_peer_details", False))
        details_chk = ttk.Checkbutton(
            frame_discovery,
            text="Show peer details in list (IP/port/last seen)",
            variable=details_chk_var,
        )
        details_chk.pack(side=tk.LEFT, padx=(8, 0))

        # Partial cleanup preferences
        frame_cleanup = ttk.Frame(dialog)
        frame_cleanup.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_cleanup, text="Auto-clean .partial older than (days):").pack(
            side=tk.LEFT
        )
        try:
            default_days = getattr(self, "partial_cleanup_days", 30)
        except Exception:
            default_days = 30
        cleanup_var = tk.IntVar(value=default_days)
        cleanup_entry = ttk.Entry(frame_cleanup, textvariable=cleanup_var, width=6)
        cleanup_entry.pack(side=tk.LEFT, padx=5)
        auto_cleanup_var = tk.BooleanVar(
            value=getattr(self, "auto_cleanup_partial", False)
        )
        auto_cleanup_chk = ttk.Checkbutton(
            frame_cleanup,
            text="Enable automatic cleanup on startup",
            variable=auto_cleanup_var,
        )
        auto_cleanup_chk.pack(side=tk.LEFT, padx=8)

        # Save folder
        frame_dir = ttk.Frame(dialog)
        frame_dir.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_dir, text="Save Folder:").pack(anchor=tk.W)
        dir_var = tk.StringVar(value=self.output_dir_var.get())
        dir_entry = ttk.Entry(frame_dir, textvariable=dir_var)
        dir_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=5)

        def _browse_prefs_dir():
            d = filedialog.askdirectory(title="Select save folder")
            if d:
                try:
                    dir_var.set(os.path.abspath(d))
                except Exception:
                    dir_var.set(d)

        ttk.Button(frame_dir, text="Browse", command=_browse_prefs_dir).pack(
            side=tk.LEFT
        )

        # Buttons
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)

        def _save_prefs():
            # Validate port
            try:
                int(recv_port_var.get().strip())
            except ValueError:
                messagebox.showerror("Error", "Port must be a number.")
                return
            self.machine_name_entry.delete(0, tk.END)
            self.machine_name_entry.insert(0, name_var.get().strip())
            self.receive_port_entry.delete(0, tk.END)
            self.receive_port_entry.insert(0, recv_port_var.get().strip())
            self.output_dir_var.set(dir_var.get().strip())
            # If server is running, update its output directory immediately
            try:
                new_dir = dir_var.get().strip()
                if new_dir:
                    try:
                        new_dir = os.path.abspath(new_dir)
                    except Exception:
                        pass
                    if getattr(self, 'server_running', False) and getattr(self, '_server_instance', None):
                        try:
                            os.makedirs(new_dir, exist_ok=True)
                        except Exception:
                            pass
                        try:
                            self._server_instance.output_dir = Path(new_dir)
                            self._log_receive(f"Updated server output_dir to: {new_dir}")
                        except Exception:
                            pass
            except Exception:
                pass
            # Save discovery preference
            try:
                self.broadcast_only_var.set(discover_chk_var.get())
            except Exception:
                pass

            # If discovery exists, restart it with new port
            try:
                new_port = int(recv_port_var.get().strip())
                # Use hostname as machine name to keep consistency
                self._start_discovery(socket.gethostname(), new_port)
            except Exception:
                pass

            # Persist config (broadcast-only preference)
            try:
                self._write_config()
            except Exception:
                pass

            # Save partial cleanup prefs
            try:
                self.partial_cleanup_days = int(cleanup_var.get())
            except Exception:
                self.partial_cleanup_days = 30
            try:
                self.auto_cleanup_partial = bool(auto_cleanup_var.get())
            except Exception:
                self.auto_cleanup_partial = False

            # Save peer details preference
            try:
                self.show_peer_details = bool(details_chk_var.get())
            except Exception:
                self.show_peer_details = False

            # Immediately refresh machines list to reflect new preference
            try:
                self._update_machines_list()
            except Exception:
                pass

            dialog.destroy()

        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btn_frame, text="Save", command=_save_prefs).pack(
            side=tk.RIGHT, padx=5
        )
        try:
            self._ensure_dialog_visible(dialog)
        except Exception:
            pass

    def _create_send_tab(self):
        """Create the send file tab"""

        main_frame = ttk.Frame(self.send_frame)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Receiver selection
        left_frame = ttk.LabelFrame(main_frame, text="Receiver Selection")
        left_frame.pack(side=tk.LEFT, fill="both", expand=True, padx=5, pady=5)

        ttk.Label(left_frame, text="Discovered Machines:").pack(
            anchor=tk.W, padx=5, pady=5
        )

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.machines_tree = ttk.Treeview(list_frame, show="tree", height=8)
        scrollbar = ttk.Scrollbar(list_frame)

        self.machines_tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.machines_tree.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.machines_tree.yview)
        self.machines_tree.bind("<<TreeviewSelect>>", self._on_machine_select)

        self._item_to_name = {}

        refresh_frame = ttk.Frame(left_frame)
        refresh_frame.pack(fill="x", padx=5, pady=5)
        ttk.Button(
            refresh_frame, text="Refresh Discovery", command=self._refresh_discovery
        ).pack(side=tk.LEFT)

        manual_frame = ttk.LabelFrame(left_frame, text="Manual Connection")
        manual_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(manual_frame, text="IP Address:").grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.host_entry = ttk.Entry(manual_frame, width=15)
        self.host_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(manual_frame, text="Port:").grid(
            row=0, column=2, sticky=tk.W, padx=5, pady=2
        )
        self.send_port_entry = ttk.Entry(manual_frame, width=8)
        self.send_port_entry.insert(0, "5000")
        self.send_port_entry.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        right_frame = ttk.LabelFrame(main_frame, text="File Transfer")
        right_frame.pack(side=tk.RIGHT, fill="both", expand=True, padx=5, pady=5)

        ttk.Label(right_frame, text="Files/Folders to send:").pack(
            anchor=tk.W, padx=5, pady=5
        )

        file_frame = ttk.Frame(right_frame)
        file_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.files_listbox = tk.Listbox(file_frame, height=6)
        file_scrollbar = ttk.Scrollbar(file_frame)

        self.files_listbox.pack(side=tk.LEFT, fill="both", expand=True)
        file_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.files_listbox.config(yscrollcommand=file_scrollbar.set)
        file_scrollbar.config(command=self.files_listbox.yview)

        try:
            if TKDND_AVAILABLE and DND_FILES:

                self.files_listbox.drop_target_register(DND_FILES)
                self.files_listbox.dnd_bind("<<Drop>>", self._on_files_dropped)
        except Exception:
            pass

        # Fallback: bind Ctrl+V for clipboard paste if DnD not available
        try:
            if not TKDND_AVAILABLE:
                self.files_listbox.bind("<Control-v>", lambda e: self._paste_files_from_clipboard())
        except Exception:
            pass

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", padx=5, pady=5)

        add_file_btn = ttk.Button(
            btn_frame, text="📄 Add File(s)", command=self._browse_files_multiple
        )
        add_file_btn.pack(side=tk.LEFT, padx=2)
        if TKDND_AVAILABLE:
            self._create_tooltip(add_file_btn, "Select one or more files to send (or drag & drop onto list)")
        else:
            self._create_tooltip(add_file_btn, "Select one or more files to send (drag & drop: copy files, Ctrl+V to paste)")

        add_folder_btn = ttk.Button(
            btn_frame, text="📁 Add Folder", command=self._browse_directory_to_send
        )
        add_folder_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(add_folder_btn, "Select a folder to send recursively")

        remove_btn = ttk.Button(
            btn_frame, text="❌ Remove", command=self._remove_selected_file
        )
        remove_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(remove_btn, "Remove selected file from the list")

        clear_btn = ttk.Button(
            btn_frame, text="🗑 Clear All", command=self._clear_all_files
        )
        clear_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(clear_btn, "Clear all files from the list")

        receiver_info_frame = ttk.LabelFrame(right_frame, text="Selected Receiver")
        receiver_info_frame.pack(anchor=tk.W, padx=5, pady=8, fill="x")
        self.selected_receiver_var = tk.StringVar(value="🔴 No receiver selected")
        self.selected_receiver_label = ttk.Label(
            receiver_info_frame,
            textvariable=self.selected_receiver_var,
            font=("Arial", 10, "bold"),
            foreground="darkgreen",
        )
        self.selected_receiver_label.pack(anchor=tk.W, padx=5, pady=4)
        # Discovery mode indicator for Send tab (shows broadcast vs multicast)
        self.send_discovery_var = tk.StringVar(value="Discovery: unknown")
        # Show discovery mode in blue for consistency with Receive tab
        self.send_discovery_label = ttk.Label(
            receiver_info_frame, textvariable=self.send_discovery_var, foreground="blue"
        )
        self.send_discovery_label.pack(anchor=tk.W, padx=5, pady=(0,4))

        send_row = ttk.Frame(right_frame)
        # Match horizontal padding with other control rows for visual alignment
        send_row.pack(pady=10, fill="x", padx=5)

        self.send_btn = ttk.Button(
            send_row, text="▶ SEND FILES", command=self._send_file
        )
        self.send_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(self.send_btn, "Start file transfer to selected receiver (or pause/resume during transfer)")

        # Pause button (hidden until transfer starts)
        self.pause_btn = ttk.Button(
            send_row, text="⏸ PAUSE", command=self._toggle_transfer_pause, state="disabled"
        )
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(self.pause_btn, "Pause/resume ongoing file transfer")

        self.resumable_status_var = tk.StringVar(value="Resumable: Off")
        self.resumable_status_label = ttk.Label(
            send_row, textvariable=self.resumable_status_var
        )
        self.resumable_status_label.pack(side=tk.LEFT, padx=(10, 0))

        progress_frame = ttk.Frame(right_frame)
        progress_frame.pack(fill="x", padx=5, pady=5)
        self.send_progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.send_progress.pack(side=tk.LEFT, fill="x", expand=True)
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_percent_label = ttk.Label(
            progress_frame,
            textvariable=self.progress_percent_var,
            width=5,
            font=("Arial", 9),
        )
        self.progress_percent_label.pack(side=tk.LEFT, padx=5)

        bytes_frame = ttk.Frame(right_frame)
        bytes_frame.pack(fill="x", padx=5, pady=2)
        self.bytes_transferred_var = tk.StringVar(value="0 B / 0 B")
        ttk.Label(
            bytes_frame, textvariable=self.bytes_transferred_var, font=("Arial", 9)
        ).pack(side=tk.LEFT)

        info_frame = ttk.Frame(right_frame)
        info_frame.pack(fill="x", padx=5)
        self.speed_var = tk.StringVar(value="Speed: -")
        self.eta_file_var = tk.StringVar(value="ETA file: -")
        self.eta_total_var = tk.StringVar(value="ETA total: -")
        ttk.Label(info_frame, textvariable=self.speed_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(info_frame, textvariable=self.eta_file_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(info_frame, textvariable=self.eta_total_var).pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(right_frame, text="Transfer Log")
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)

        log_ctrl_frame = ttk.Frame(log_frame)
        log_ctrl_frame.pack(fill="x", padx=5, pady=3)

        ttk.Label(log_ctrl_frame, text="Filter:").pack(side=tk.LEFT, padx=(0, 5))
        self.send_log_filter = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(
            log_ctrl_frame,
            textvariable=self.send_log_filter,
            values=["All", "INFO", "ERROR", "WARNING"],
            state="readonly",
            width=10,
        )
        filter_combo.pack(side=tk.LEFT, padx=2)
        filter_combo.bind(
            "<<ComboboxSelected>>", lambda e: self._apply_log_filter("send")
        )

        ttk.Button(
            log_ctrl_frame, text="🗑 Clear", command=lambda: self._clear_log("send")
        ).pack(side=tk.RIGHT, padx=2)

        self.send_log = scrolledtext.ScrolledText(
            log_frame, height=12, state="disabled", font=("Courier", 8)
        )
        self.send_log.pack(fill="both", expand=True)

    def _create_receive_tab(self):
        """Create the receive files tab"""
        main_frame = ttk.Frame(self.receive_frame)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        left_frame = ttk.LabelFrame(main_frame, text="Receiver Configuration")
        left_frame.pack(side=tk.LEFT, fill="both", padx=5, pady=5)

        # Machine name (kept for display but discovery uses hostname)
        ttk.Label(left_frame, text="Machine Name:").pack(anchor=tk.W, padx=5, pady=2)
        self.machine_name_entry = ttk.Entry(left_frame)
        self.machine_name_entry.insert(0, socket.gethostname())
        self.machine_name_entry.pack(fill="x", padx=5, pady=2)

        # Port
        ttk.Label(left_frame, text="Listen Port:").pack(anchor=tk.W, padx=5, pady=2)
        self.receive_port_entry = ttk.Entry(left_frame)
        self.receive_port_entry.insert(0, "5000")
        self.receive_port_entry.pack(fill="x", padx=5, pady=2)

        # Output directory
        ttk.Label(left_frame, text="Save Files To:").pack(anchor=tk.W, padx=5, pady=2)

        dir_frame = ttk.Frame(left_frame)
        dir_frame.pack(fill="x", padx=5, pady=2)

        self.output_dir_var = tk.StringVar(
            value=os.path.join(os.getcwd(), "ReceivedFiles")
        )
        self.dir_entry = ttk.Entry(dir_frame, textvariable=self.output_dir_var)
        self.dir_entry.pack(side=tk.LEFT, fill="x", expand=True)

        ttk.Button(dir_frame, text="Browse", command=self._browse_directory).pack(
            side=tk.RIGHT, padx=(5, 0)
        )

        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill="x", padx=5, pady=10)

        self.start_server_btn = ttk.Button(
            btn_frame, text="▶ Start Receiver", command=self._start_server
        )
        self.start_server_btn.pack(side=tk.LEFT, padx=(0, 5))
        self._create_tooltip(
            self.start_server_btn, "Start listening for incoming file transfers"
        )

        self.stop_server_btn = ttk.Button(
            btn_frame,
            text="⏹ Stop Receiver",
            command=self._stop_server,
            state="disabled",
        )
        self.stop_server_btn.pack(side=tk.LEFT)
        self._create_tooltip(
            self.stop_server_btn, "Stop listening for incoming file transfers"
        )

        status_frame = ttk.Frame(left_frame)
        status_frame.pack(anchor=tk.W, padx=5, pady=5)
        self.server_status_icon = ttk.Label(
            status_frame, text="●", foreground="red", font=("Arial", 10)
        )
        self.server_status_icon.pack(side=tk.LEFT)
        self.server_status_label = ttk.Label(
            status_frame, text=" Status: Stopped", foreground="red"
        )
        self.server_status_label.pack(side=tk.LEFT)

        local_ip = self._get_local_ip()
        ip_label = ttk.Label(left_frame, text=f"Your IP: {local_ip}", foreground="blue")
        ip_label.pack(anchor=tk.W, padx=5, pady=2)

        self.discovery_mode_var = tk.StringVar(value="Discovery: unknown")
        discovery_mode_label = ttk.Label(
            left_frame, textvariable=self.discovery_mode_var, foreground="blue"
        )
        discovery_mode_label.pack(anchor=tk.W, padx=5, pady=2)

        # (Broadcast-only toggle removed from main UI; available in Preferences)

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill="both", expand=True, padx=5, pady=5)

        # Receiver log with controls
        log_frame = ttk.LabelFrame(right_frame, text="Receiver Log")
        log_frame.pack(fill="both", expand=True, padx=0, pady=(0, 5))

        log_ctrl_frame = ttk.Frame(log_frame)
        log_ctrl_frame.pack(fill="x", padx=5, pady=3)

        ttk.Label(log_ctrl_frame, text="Filter:").pack(side=tk.LEFT, padx=(0, 5))
        self.recv_log_filter = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(
            log_ctrl_frame,
            textvariable=self.recv_log_filter,
            values=["All", "INFO", "ERROR", "WARNING"],
            state="readonly",
            width=10,
        )
        filter_combo.pack(side=tk.LEFT, padx=2)
        filter_combo.bind(
            "<<ComboboxSelected>>", lambda e: self._apply_log_filter("recv")
        )

        ttk.Button(
            log_ctrl_frame, text="🗑 Clear", command=lambda: self._clear_log("recv")
        ).pack(side=tk.RIGHT, padx=2)

        self.receive_log = scrolledtext.ScrolledText(
            log_frame, height=12, state="disabled", font=("Courier", 8)
        )
        self.receive_log.pack(fill="both", expand=True)

        # Receive progress area
        recv_progress_frame = ttk.Frame(right_frame)
        recv_progress_frame.pack(fill="x", padx=5, pady=(5, 8))
        self.recv_progress = ttk.Progressbar(recv_progress_frame, mode="determinate")
        self.recv_progress.pack(side=tk.LEFT, fill="x", expand=True)
        self.recv_progress_percent_var = tk.StringVar(value="0%")
        ttk.Label(recv_progress_frame, textvariable=self.recv_progress_percent_var, width=6).pack(side=tk.LEFT, padx=6)

        recv_bytes_frame = ttk.Frame(right_frame)
        recv_bytes_frame.pack(fill="x", padx=5, pady=(0, 4))
        self.recv_bytes_var = tk.StringVar(value="0 B / 0 B")
        ttk.Label(recv_bytes_frame, textvariable=self.recv_bytes_var).pack(side=tk.LEFT)
        self.recv_speed_var = tk.StringVar(value="Speed: -")
        ttk.Label(recv_bytes_frame, textvariable=self.recv_speed_var).pack(side=tk.LEFT, padx=(10, 0))
        self.recv_eta_var = tk.StringVar(value="ETA: -")
        ttk.Label(recv_bytes_frame, textvariable=self.recv_eta_var).pack(side=tk.LEFT, padx=(10, 0))

        # Recent files list
        recent_frame = ttk.LabelFrame(right_frame, text="Recently Received Files")
        recent_frame.pack(fill="both", expand=True, padx=0)

        self.recent_files_listbox = tk.Listbox(
            recent_frame, height=6, font=("Arial", 9)
        )
        recent_scrollbar = ttk.Scrollbar(recent_frame)
        self.recent_files_listbox.pack(
            side=tk.LEFT, fill="both", expand=True, padx=5, pady=5
        )
        recent_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.recent_files_listbox.config(yscrollcommand=recent_scrollbar.set)
        recent_scrollbar.config(command=self.recent_files_listbox.yview)
        # Bind double-click to open containing folder and select file
        try:
            self.recent_files_listbox.bind("<Double-1>", self._on_recent_double_click)
        except Exception:
            pass

        # Track recently received files as list of dicts {'path': fullpath, 'display': display}
        self.recent_received_files = []

    def _create_magi_tab(self):
        """Create the MAGI System Console tab with boot sequence and dynamic data."""
        # Main frame with dark background
        main_frame = tk.Frame(self.magi_frame, bg="#000000")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Console text widget
        self.magi_console = tk.Text(
            main_frame,
            bg="#000000",
            fg="#00ffaa",
            font=("Courier", 10),
            state="disabled",
            wrap=tk.WORD,
        )
        self.magi_console.pack(fill="both", expand=True, padx=5, pady=5)

        # Tag for styling different console lines
        self.magi_console.tag_configure("header", foreground="#00ffff", font=("Courier", 10, "bold"))
        self.magi_console.tag_configure("success", foreground="#00ff00")
        self.magi_console.tag_configure("status", foreground="#ffff00")
        self.magi_console.tag_configure("error", foreground="#ff0000")
        self.magi_console.tag_configure("system", foreground="#00ffaa")

        # Scrollbar
        scrollbar = ttk.Scrollbar(main_frame, command=self.magi_console.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.magi_console.config(yscrollcommand=scrollbar.set)

    def _show_magi_tab(self):
        """Add MAGI Console tab to notebook and start boot sequence."""
        try:
            # Check if tab already exists (don't add twice)
            if self.magi_frame.winfo_manager():
                return
            
            # Insert MAGI tab before About tab (before last tab)
            self.notebook.insert(2, self.magi_frame, text="⚡ MAGI Console")
            self.root.after(300, self._start_magi_boot_sequence)
        except Exception:
            pass

    def _hide_magi_tab(self):
        """Remove MAGI Console tab from notebook."""
        try:
            # Find and remove MAGI tab by checking all tab IDs
            tabs = self.notebook.tabs()
            for tab_id in tabs:
                try:
                    # Get the frame associated with this tab
                    if tab_id == str(self.magi_frame):
                        self.notebook.forget(tab_id)
                        break
                except Exception:
                    pass
        except Exception:
            pass

    def _write_magi_line(self, text, tag="system"):
        """Write a line to the MAGI console with specified tag."""
        try:
            self.magi_console.config(state="normal")
            self.magi_console.insert(tk.END, text + "\n", tag)
            self.magi_console.see(tk.END)
            self.magi_console.config(state="disabled")
            self.magi_console.update()
        except Exception:
            pass

    def _start_magi_boot_sequence(self):
        """Start the animated MAGI boot sequence (one-time animation, no loop)."""
        try:
            # Clear console
            self.magi_console.config(state="normal")
            self.magi_console.delete("1.0", tk.END)
            self.magi_console.config(state="disabled")

            # Get dynamic data once
            connection = self._get_magi_connection_status()
            latency = self._get_magi_latency()
            packet_loss = self._get_magi_packet_loss()
            bandwidth = self._get_magi_bandwidth()
            
            transfer_speed = self._get_magi_transfer_speed()
            files_sent = self._get_magi_files_sent()
            files_pending = self._get_magi_files_pending()
            
            cpu_load = self._get_magi_cpu_load()
            memory_usage = self._get_magi_memory_usage()
            device_status = self._get_magi_device_status()
            
            auth_status = self._get_magi_auth_status()
            encryption = self._get_magi_encryption()

            # Complete boot sequence + status in single animation
            boot_lines = [
                ("", "system"),
                ("[MAGI SYSTEM BOOT v1.0]", "header"),
                (">>> INITIALIZING MODULES", "status"),
                ("   Melchior ............. OK", "success"),
                ("   Balthasar ............ OK", "success"),
                ("   Casper ............... OK", "success"),
                (">>> SYNCHRONIZATION .... COMPLETE", "status"),
                (">>> TRINARY DECISION ENGINE ONLINE", "status"),
                ("", "system"),
                ("[CONNECTION STATUS]", "header"),
                (f"CONNECTION: {connection}", "system"),
                (f"LATENCY: {latency}", "system"),
                (f"PACKET LOSS: {packet_loss}", "system"),
                (f"BANDWIDTH: {bandwidth}", "system"),
                ("", "system"),
                ("[TRANSFER MODULE]", "header"),
                (f"TRANSFER SPEED: {transfer_speed}", "system"),
                (f"FILES SENT: {files_sent}", "system"),
                (f"FILES PENDING: {files_pending}", "system"),
                ("", "system"),
                ("[DEVICE STATUS]", "header"),
                (f"CPU LOAD: {cpu_load}", "system"),
                (f"MEMORY USAGE: {memory_usage}", "system"),
                (f"DEVICE STATUS: {device_status}", "system"),
                ("", "system"),
                ("[SECURITY CHECK]", "header"),
                (f"AUTH STATUS: {auth_status}", "system"),
                (f"ENCRYPTION: {encryption}", "system"),
                ("", "system"),
                (">>> MAGI SYSTEM READY", "status"),
            ]

            # Write lines with animation (one-time, no loop)
            for idx, (line, tag) in enumerate(boot_lines):
                try:
                    self.root.after(idx * 150, lambda l=line, t=tag: self._write_magi_line(l, t))
                except Exception:
                    pass
        except Exception:
            pass

    # MAGI Dynamic Data Functions
    def _get_magi_connection_status(self):
        """Get connection status."""
        try:
            if self.discovery and self.discovery.get_peers():
                return "ONLINE"
            return "OFFLINE"
        except Exception:
            return "UNKNOWN"

    def _get_magi_latency(self):
        """Get simulated latency (ms)."""
        try:
            import random
            return f"{random.randint(1, 50)} ms"
        except Exception:
            return "N/A"

    def _get_magi_packet_loss(self):
        """Get simulated packet loss."""
        try:
            import random
            return f"{random.randint(0, 2)}%"
        except Exception:
            return "N/A"

    def _get_magi_bandwidth(self):
        """Get simulated bandwidth usage."""
        try:
            import random
            return f"{random.randint(10, 95)} Mbps"
        except Exception:
            return "N/A"

    def _get_magi_transfer_speed(self):
        """Get current transfer speed."""
        try:
            if self.server_running:
                import random
                return f"{random.randint(5, 50)} MB/s"
            return "0 MB/s"
        except Exception:
            return "N/A"

    def _get_magi_files_sent(self):
        """Get count of files sent."""
        try:
            sent_count = sum(1 for e in self.transfer_history if e.get('type') == 'send')
            return str(sent_count)
        except Exception:
            return "0"

    def _get_magi_files_pending(self):
        """Get simulated pending files."""
        try:
            import random
            return str(random.randint(0, 5))
        except Exception:
            return "0"

    def _get_magi_cpu_load(self):
        """Get simulated CPU load."""
        try:
            import random
            return f"{random.randint(5, 45)}%"
        except Exception:
            return "N/A"

    def _get_magi_memory_usage(self):
        """Get simulated memory usage."""
        try:
            import random
            return f"{random.randint(100, 500)} MB"
        except Exception:
            return "N/A"

    def _get_magi_device_status(self):
        """Get device status."""
        try:
            return "OPERATIONAL"
        except Exception:
            return "UNKNOWN"

    def _get_magi_auth_status(self):
        """Get authentication status."""
        try:
            return "AUTHORIZED"
        except Exception:
            return "UNKNOWN"

    def _get_magi_encryption(self):
        """Get encryption status."""
        try:
            return "AES-256 ENABLED"
        except Exception:
            return "DISABLED"

    def _create_about_tab(self):
        """Create the About tab with scrollbar - centered layout"""
        # Main container with scrollbar
        main_container = ttk.Frame(self.about_frame)
        main_container.pack(fill="both", expand=True)

        # Create canvas and scrollbar
        canvas = tk.Canvas(main_container, bg="#f0f0f0", highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            main_container, orient="vertical", command=canvas.yview
        )
        scrollable_frame = ttk.Frame(canvas)

        # Configure the canvas
        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # Center the content
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        # Inner container to center content horizontally
        content_container = ttk.Frame(scrollable_frame)
        content_container.pack(fill="both", expand=True, padx=20)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Application header - centered inside content container
        header_frame = ttk.Frame(content_container)
        header_frame.pack(pady=(0, 20), anchor="center")

        # Application title with larger font
        title_label = ttk.Label(
            header_frame,
            text="NetLink",
            font=("Arial", 18, "bold"),
            foreground="#0066cc",
        )
        title_label.pack(pady=(0, 10), anchor="center")

        # Version info with beta badge
        version_frame = ttk.Frame(header_frame)
        version_frame.pack(anchor="center")

        version_label = ttk.Label(
            version_frame, text=f"v{VERSION}", font=("Arial", 10, "bold"), foreground="#555555"
        )
        version_label.pack(side=tk.LEFT, padx=(0, 15))

        # Beta testing badge
        beta_label = ttk.Label(
            version_frame,
            text="BETA TESTING",
            font=("Arial", 8, "bold"),
            foreground="white",
            background="#e74c3c",
            padding=(6, 2),
        )
        beta_label.pack(side=tk.LEFT)
        try:
            # Bind clicks to the easter-egg handler (7 clicks activates)
            beta_label.bind("<Button-1>", lambda e: self._on_beta_click())
        except Exception:
            pass

        # Hidden NERV authorization label (shown when NERV Mode active)
        try:
            self.nerv_status_label = ttk.Label(
                header_frame,
                text="NERV AUTHORIZATION LEVEL 3 CONFIRMED.",
                font=("Courier", 9, "bold"),
                foreground="#ff4444",
            )
            # do not pack now; shown only when NERV mode is active
        except Exception:
            self.nerv_status_label = None

        # Separator
        ttk.Separator(content_container, orient="horizontal").pack(
            fill="x", pady=20
        )

        # Features section
        features_frame = ttk.LabelFrame(content_container, text="Features")
        features_frame.pack(fill="x", pady=(0, 20), anchor="center")

        features_text = """
• Cross-platform compatibility (Windows, macOS, Linux)
• No external dependencies - Pure Python
• Automatic network discovery
• Secure local file transfers
• Real-time progress monitoring
• User-friendly graphical interface
• Support for large file transfers
• Easy to use and setup
• No installation required
• Open source project
• Regular updates and improvements
• Community driven development
"""
        features_label = ttk.Label(
            features_frame, text=features_text, justify=tk.LEFT, font=("Arial", 9)
        )
        features_label.pack(padx=10, pady=10, anchor=tk.W)

        # Author information
        author_frame = ttk.LabelFrame(content_container, text="Developer Information")
        author_frame.pack(fill="x", pady=(0, 20), anchor="center")

        author_text = """
Developed by: Scorpionziky

This application was created to provide a simple, reliable 
file transfer solution for local networks without requiring 
any additional software installations.

The project aims to make file sharing between computers on 
the same network as easy as possible, while maintaining 
security and performance.

If you encounter any issues or have suggestions for 
improvements, please don't hesitate to contact me using 
the methods below.
"""
        author_label = ttk.Label(
            author_frame, text=author_text, justify=tk.LEFT, font=("Arial", 9)
        )
        author_label.pack(padx=10, pady=10, anchor=tk.W)

        # Contact methods
        contact_frame = ttk.LabelFrame(content_container, text="Contact & Support")
        contact_frame.pack(fill="x", pady=(0, 20), anchor="center")

        # Documentation links (create .txt on demand from .md and open)
        links_frame = ttk.LabelFrame(content_container, text="Documentation")
        links_frame.pack(fill="x", pady=(0, 20), anchor="center")

        def _open_create_txt(md_name, txt_name):
            base = Path(__file__).parent
            md_path = base / md_name
            txt_path = base / txt_name
            # If .txt doesn't exist but .md does, create .txt from .md
            try:
                if not txt_path.exists() and md_path.exists():
                    try:
                        with open(md_path, 'r', encoding='utf-8') as rf:
                            content = rf.read()
                        with open(txt_path, 'w', encoding='utf-8') as wf:
                            wf.write(content)
                    except Exception:
                        pass
                # Prefer opening the .txt if exists, else open .md if exists
                if txt_path.exists():
                    webbrowser.open('file://' + str(txt_path))
                elif md_path.exists():
                    webbrowser.open('file://' + str(md_path))
            except Exception:
                pass

        ttk.Button(links_frame, text="Open QUICK_START", command=lambda: _open_create_txt('QUICK_START.md', 'QUICK_START.txt')).pack(padx=10, pady=6, anchor=tk.W)
        ttk.Button(links_frame, text="Open README", command=lambda: _open_create_txt('README.md', 'README.txt')).pack(padx=10, pady=6, anchor=tk.W)

        # Email
        email_frame = ttk.Frame(contact_frame)
        email_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(email_frame, text="Email:", font=("Arial", 9, "bold")).pack(
            side=tk.LEFT
        )
        email_link = ttk.Label(
            email_frame,
            text="scorpionziky89@gmail.com",
            font=("Arial", 9),
            foreground="#3498db",
            cursor="hand2",
        )
        email_link.pack(side=tk.LEFT, padx=(5, 0))
        email_link.bind("<Button-1>", lambda e: self._open_email_client())

        # GitHub
        github_frame = ttk.Frame(contact_frame)
        github_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(github_frame, text="GitHub:", font=("Arial", 9, "bold")).pack(
            side=tk.LEFT
        )
        github_link = ttk.Label(
            github_frame,
            text="https://github.com/scorpionziky",
            font=("Arial", 9),
            foreground="#3498db",
            cursor="hand2",
        )
        github_link.pack(side=tk.LEFT, padx=(5, 0))
        github_link.bind("<Button-1>", lambda e: self._open_github())

        # Technical info
        tech_frame = ttk.LabelFrame(scrollable_frame, text="Technical Information")
        tech_frame.pack(fill="x", padx=20, pady=(0, 20), anchor="center")

        tech_text = f"""
Python Version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}
Platform: {sys.platform}
Hostname: {socket.gethostname()}
Local IP: {self._get_local_ip()}
Application Directory: {os.path.dirname(os.path.abspath(__file__))}
"""
        tech_label = ttk.Label(
            tech_frame,
            text=tech_text,
            justify=tk.LEFT,
            font=("Arial", 8),
            foreground="#7f8c8d",
        )
        tech_label.pack(padx=10, pady=10, anchor=tk.W)

        # Additional information
        info_frame = ttk.LabelFrame(scrollable_frame, text="Additional Information")
        info_frame.pack(fill="x", padx=20, pady=(0, 20), anchor="center")

        info_text = """
This application is built using Python's standard library only, 
making it lightweight and portable. It uses TCP sockets for 
reliable file transfers and UDP multicast for service discovery.

The application is designed for use on trusted local networks 
only. For security reasons, it does not include encryption or 
authentication features.

If you enjoy using this application, consider starring the 
project on GitHub or contributing to its development!
"""
        info_label = ttk.Label(
            info_frame,
            text=info_text,
            justify=tk.LEFT,
            font=("Arial", 8),
            foreground="#7f8c8d",
        )
        info_label.pack(padx=10, pady=10, anchor=tk.W)

        # Copyright notice
        copyright_label = ttk.Label(
            scrollable_frame,
            text="© 2025 Scorpionziky All rights reserved.",
            font=("Arial", 8),
            foreground="#95a5a6",
        )
        copyright_label.pack(pady=(20, 30))

        # Configure mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # For Linux
        def _on_scroll_up(event):
            canvas.yview_scroll(-1, "units")

        def _on_scroll_down(event):
            canvas.yview_scroll(1, "units")

        canvas.bind_all("<Button-4>", _on_scroll_up)
        canvas.bind_all("<Button-5>", _on_scroll_down)

    # -------------------------
    # Utilities: browse, log, etc.
    # -------------------------
    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget."""

    # -------------------------
    # Easter-egg: NERV emergency and theme
    # -------------------------
    def _on_beta_click(self):
        """Handle clicks on the BETA label. 7 clicks toggles/activates NERV."""
        try:
            self._beta_click_count = getattr(self, '_beta_click_count', 0) + 1
            # reset counter if too large
            if self._beta_click_count > 7:
                self._beta_click_count = 1

            if self._beta_click_count >= 7:
                # Reset counter
                self._beta_click_count = 0
                # Toggle behavior: if already in nerv mode, deactivate; otherwise show emergency + activate
                if getattr(self, '_nerv_mode', False):
                    try:
                        self._deactivate_nerv_mode()
                    except Exception:
                        pass
                else:
                    try:
                        # Show emergency modal and play NERV beep
                        self._show_nerv_emergency_modal()
                    except Exception:
                        pass
                    try:
                        # Activate NERV theme after showing modal
                        self._activate_nerv_mode()
                    except Exception:
                        pass
        except Exception:
            pass

    def _play_nerv_beep(self):
        """Play a short sequence of beeps similar to the NERV alert (Windows fallback to bell)."""
        try:
            if sys.platform.startswith("win"):
                try:
                    import winsound

                    # A short sequence of two beeps
                    winsound.Beep(750, 300)
                    time.sleep(0.12)
                    winsound.Beep(1000, 220)
                except Exception:
                    try:
                        self.root.bell()
                        time.sleep(0.1)
                        self.root.bell()
                    except Exception:
                        pass
            else:
                try:
                    # Non-Windows: use bell twice
                    self.root.bell()
                    time.sleep(0.12)
                    self.root.bell()
                except Exception:
                    pass
        except Exception:
            pass

    def _activate_nerv_mode(self):
        """Show NERV status text, reveal MAGI Console tab, and log activation."""
        try:
            if getattr(self, '_nerv_mode', False):
                return
            self._nerv_mode = True

            # Show the small NERV confirmation under the header if present
            try:
                if getattr(self, 'nerv_status_label', None):
                    try:
                        self.nerv_status_label.pack(pady=(4, 10))
                    except Exception:
                        pass
            except Exception:
                pass

            # Show MAGI Console tab
            try:
                self._show_magi_tab()
            except Exception:
                pass

            # Save NERV mode state to config
            try:
                self._write_config()
            except Exception:
                pass

            # Log activation
            try:
                self._log_send("[EasterEgg] NERV Mode activated")
            except Exception:
                pass
        except Exception:
            pass

    def _deactivate_nerv_mode(self):
        """Hide NERV status text, hide MAGI Console tab, and log deactivation."""
        try:
            if not getattr(self, '_nerv_mode', False):
                return
            self._nerv_mode = False

            try:
                if getattr(self, 'nerv_status_label', None):
                    try:
                        self.nerv_status_label.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass

            # Hide MAGI Console tab
            try:
                self._hide_magi_tab()
            except Exception:
                pass

            # Save NERV mode state to config
            try:
                self._write_config()
            except Exception:
                pass

            try:
                self._log_send("[EasterEgg] NERV Mode deactivated")
            except Exception:
                pass

            try:
                messagebox.showinfo("NERV Mode", "NERV Mode deactivated.")
            except Exception:
                pass
        except Exception:
            pass

    def _restore_nerv_mode_on_startup(self):
        """Restore NERV mode on startup if it was previously activated."""
        try:
            if getattr(self, '_nerv_mode', False):
                # Show NERV label
                try:
                    if getattr(self, 'nerv_status_label', None):
                        try:
                            self.nerv_status_label.pack(pady=(4, 10))
                        except Exception:
                            pass
                except Exception:
                    pass

                # Show MAGI Console tab
                try:
                    self._show_magi_tab()
                except Exception:
                    pass

                try:
                    self._log_send("[EasterEgg] NERV Mode restored from config")
                except Exception:
                    pass
        except Exception:
            pass

        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = ttk.Label(
                tooltip, text=text, background="#ffffe0", relief=tk.SOLID, borderwidth=1
            )
            label.pack()
            widget.tooltip = tooltip

        def on_leave(event):
            if hasattr(widget, "tooltip"):
                widget.tooltip.destroy()
                delattr(widget, "tooltip")

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _clear_log(self, log_type: str):
        """Clear specified log."""
        if log_type == "send":
            self.send_log.config(state="normal")
            self.send_log.delete("1.0", tk.END)
            self.send_log.config(state="disabled")
        elif log_type == "recv":
            self.receive_log.config(state="normal")
            self.receive_log.delete("1.0", tk.END)
            self.receive_log.config(state="disabled")

    def _apply_log_filter(self, log_type: str):
        """Apply filter to log display (currently placeholder; could be extended)."""
        pass

    def _add_recent_file(self, filename: str, filesize: int):
        """Add file to recently received files list."""
        try:
            size_str = self._format_file_size(filesize)
            # If filename is an absolute path, show only basename in the list but
            # keep the full path for selection. If it's relative, compute fullpath
            # by joining with configured output directory.
            try:
                p = Path(filename)
                if p.is_absolute():
                    fullpath = str(p)
                    display_name = os.path.basename(fullpath)
                else:
                    fullpath = os.path.join(self.output_dir_var.get(), filename)
                    display_name = filename
            except Exception:
                fullpath = os.path.join(self.output_dir_var.get(), filename)
                display_name = os.path.basename(fullpath)

            display = f"{display_name} ({size_str})"

            # Keep only last 20 files
            if len(self.recent_received_files) >= 20:
                self.recent_files_listbox.delete(0, 0)
                self.recent_received_files.pop(0)
            self.recent_received_files.append({"path": fullpath, "display": display})
            self.recent_files_listbox.insert(tk.END, display)
            self.recent_files_listbox.see(tk.END)
        except Exception:
            pass

    def _update_tab_badge(self):
        """Update badge on Receive Files tab when files arrive."""
        try:
            # Use a stable unicode icon for the tab and show count when available.
            if self.recent_received_files:
                try:
                    count = len(self.recent_received_files)
                    # inbox tray emoji + count
                    self.notebook.tab(1, text=f"📥 Receive Files ({count})")
                except Exception:
                    self.notebook.tab(1, text="📥 Receive Files")
            else:
                self.notebook.tab(1, text="Receive Files")
        except Exception:
            pass

    def _open_email_client(self):
        """Open default email client"""
        try:
            webbrowser.open("mailto:scorpionziky89@gmail.com")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open email client: {e}")

    def _open_github(self):
        """Open GitHub page"""
        try:
            webbrowser.open("https://github.com/scorpionziky")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open GitHub: {e}")

    def _ensure_dialog_visible(self, dialog: tk.Toplevel):
        """Ensure dialog has a reasonable size and is centered so bottom buttons are visible.

        This addresses cases where dialogs are created too small and buttons at the bottom
        are not visible until user resizes the window.
        """
        try:
            dialog.update_idletasks()
            # requested size
            w = dialog.winfo_reqwidth()
            h = dialog.winfo_reqheight()
            # screen size
            try:
                sw = dialog.winfo_screenwidth()
                sh = dialog.winfo_screenheight()
                x = max(0, (sw - w) // 2)
                y = max(0, (sh - h) // 2)
                dialog.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
            try:
                dialog.minsize(w, h)
            except Exception:
                pass
        except Exception:
            pass

    def _refresh_discovery(self):
        """Force refresh of discovered machines list"""
        self._log_send("Scanning for machines...")
        if not self.discovery:
            # Start discovery service if missing
            self.start_discovery_service()
            # give it a short moment to populate
            self.root.after(2000, self._update_machines_list)
            count = 0
        else:
            # If discovery already running, ask it to emit a beacon now
            try:
                # send an immediate beacon to speed up detection
                self.discovery.send_beacon_once()
            except Exception:
                pass
            # schedule a UI update shortly to show new peers
            self.root.after(1000, self._update_machines_list)
            count = len(self.discovery.get_peers())

        self._log_send(f"Scan complete. Found {count} machines.")

    def _on_machine_select(self, event):
        """Handle machine selection from listbox"""
        sel = self.machines_tree.selection()
        if not sel:
            return
        item = sel[0]
        machine_name = self._item_to_name.get(item)
        if not machine_name:
            return
        if self.discovery:
            peers = self.discovery.get_peers()
            peer_info = peers.get(machine_name)
            if peer_info:
                self.host_entry.delete(0, tk.END)
                self.host_entry.insert(0, peer_info["ip"])
                self.send_port_entry.delete(0, tk.END)
                self.send_port_entry.insert(0, str(peer_info["port"]))
                # Determine age and choose status color/icon
                try:
                    now = time.time()
                    last = peer_info.get("last_seen")
                    if last:
                        age = int(now - float(last))
                    else:
                        age = None
                except Exception:
                    age = None

                if age is None:
                    color = "#3498db"
                else:
                    if age < 5:
                        color = "#2ecc71"  # green
                    elif age < 30:
                        color = "#f1c40f"  # yellow
                    else:
                        color = "#95a5a6"  # gray

                # Try to get a small colored image; fallback to emoji
                status_img = self._get_status_image(color, size=14)
                display_text = f"{machine_name}\n({peer_info['ip']}:{peer_info['port']})"
                if status_img is not None:
                    self._selected_receiver_image = status_img
                    try:
                        # Use image on the left of the label
                        self.selected_receiver_label.config(image=status_img, compound='left')
                    except Exception:
                        # fallback to text-only
                        self.selected_receiver_label.config(image='')
                else:
                    # Emoji fallback
                    if color == "#2ecc71":
                        status_icon = "\U0001F7E2"  # 🟢
                    elif color == "#f1c40f":
                        status_icon = "\U0001F7E1"  # 🟡
                    elif color == "#95a5a6":
                        status_icon = "\u26AA"     # ⚪
                    else:
                        status_icon = "\u25CF"     # ●
                    display_text = f"{status_icon} {display_text}"
                    try:
                        self.selected_receiver_label.config(image='')
                    except Exception:
                        pass

                # Update label text and color
                self.selected_receiver_var.set(display_text)
                try:
                    self.selected_receiver_label.config(foreground="darkgreen")
                except Exception:
                    pass

    def _update_machines_list(self):
        """Update the list of discovered machines"""
        if not self.discovery:
            return

        peers = self.discovery.get_peers()
        now = time.time()

        # Rebuild treeview items
        for iid in self.machines_tree.get_children():
            self.machines_tree.delete(iid)
        self._machines_order = []
        self._item_to_name.clear()

        for name in sorted(peers.keys()):
            info = peers.get(name, {})
            ip = info.get("ip", "unknown")
            port = info.get("port", "")
            last_seen_ts = info.get("last_seen")

            # Apply IP filter if set
            if self.discovery_ip_filter and ip != "unknown":
                if not ip.startswith(self.discovery_ip_filter):
                    continue  # Skip this peer if it doesn't match filter

            # Determine status indicator (use reliable Unicode codepoints to avoid mojibake)
            if last_seen_ts:
                age = int(now - float(last_seen_ts))
                if age < 5:
                    status_icon = "\U0001F7E2"  # 🟢 Online
                elif age < 30:
                    status_icon = "\U0001F7E1"  # 🟡 Recently seen
                else:
                    status_icon = "\u26AA"     # ⚪ Offline/stale
                age_str = self._human_readable_age(age)
            else:
                status_icon = "\u25CB"  # ○ unknown / just seen
                age_str = "now"

            # Always show a small status indicator (emoji) next to the name so the
            # colored dot is visible in both simple and detailed modes.
            if getattr(self, "show_peer_details", False):
                # Detailed view: include status icon, IP, port and last seen
                display_name = f"{status_icon} {name} ({ip}:{port}) [{age_str}]"
            else:
                # Simple view (default): show status icon and machine name only
                display_name = f"{status_icon} {name}"

            # Insert into treeview. Prefer using a small colored image for the
            # status dot (PIL required). If not available, prefix the name
            # with a Unicode emoji as fallback.
            # Determine color for status
            if last_seen_ts:
                if age < 5:
                    color = "#2ecc71"  # green
                elif age < 30:
                    color = "#f1c40f"  # yellow
                else:
                    color = "#95a5a6"  # gray
            else:
                color = "#3498db"  # blue for unknown

            status_img = self._get_status_image(color)
            if status_img is not None:
                # Use display_name so 'show_peer_details' is respected even when an image is shown
                item = self.machines_tree.insert("", "end", text=display_name, image=status_img)
                # keep reference to avoid GC
                self._item_images[item] = status_img
            else:
                # fallback: include a colored emoji if images unavailable
                # note: some platforms may render emoji monochrome
                if color == "#2ecc71":
                    status_icon = "\U0001F7E2"  # 🟢
                elif color == "#f1c40f":
                    status_icon = "\U0001F7E1"  # 🟡
                elif color == "#95a5a6":
                    status_icon = "\u26AA"     # ⚪
                else:
                    status_icon = "\u25CF"     # ●

                # Use the precomputed display_name (may include status icon and details)
                item = self.machines_tree.insert("", "end", text=display_name)

            self._machines_order.append(name)
            self._item_to_name[item] = name

        # Log if we're discovering anything
        if (
            not peers
            and hasattr(self, "_discovery_empty_logged")
            and not self._discovery_empty_logged
        ):
            self._log_send("Waiting for other machines to broadcast...")
            self._discovery_empty_logged = True
        elif peers:
            self._discovery_empty_logged = False

    def _browse_file(self):
        """Browse for file to send (old method, kept for compatibility)"""
        filename = filedialog.askopenfilename(title="Select file to send")
        if filename:
            self.selected_files = [filename]
            self._update_files_listbox()

    def _browse_files_multiple(self):
        """Browse for multiple files to send"""
        filenames = filedialog.askopenfilenames(title="Select files to send")
        if filenames:
            self.selected_files.extend(filenames)
            self._update_files_listbox()

    def _browse_directory_to_send(self):
        """Browse for directory to send"""
        directory = filedialog.askdirectory(title="Select folder to send")
        if directory:
            self.selected_files.append(directory)
            self._update_files_listbox()

    def _update_files_listbox(self):
        """Update the listbox with selected files"""
        self.files_listbox.delete(0, tk.END)
        for filepath in self.selected_files:
            path = Path(filepath)
            if path.is_dir():
                display_text = f"[FOLDER] {path.name}"
            else:
                size = path.stat().st_size
                size_str = self._format_file_size(size)
                display_text = f"{path.name} ({size_str})"
            self.files_listbox.insert(tk.END, display_text)

    def _remove_selected_file(self):
        """Remove selected file from list"""
        selection = self.files_listbox.curselection()
        if selection:
            index = selection[0]
            del self.selected_files[index]
            self._update_files_listbox()

    def _clear_all_files(self):
        """Clear all selected files"""
        self.selected_files.clear()
        self._update_files_listbox()

    def _format_file_size(self, size):
        """Format file size in human-readable format"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def _format_transfer_speed(self, bytes_per_sec: float) -> str:
        """Format transfer speed in a human-readable string (e.g., '1.2 MB/s')."""
        try:
            bps = float(bytes_per_sec)
            if bps <= 0:
                return "-"
            units = ["B/s", "KB/s", "MB/s", "GB/s"]
            i = 0
            while bps >= 1024 and i < len(units) - 1:
                bps /= 1024.0
                i += 1
            return f"{bps:.2f} {units[i]}"
        except Exception:
            return "-"

    def _format_eta(self, seconds: int) -> str:
        """Format ETA seconds into human-readable string like '1m 3s' or '-' if unknown."""
        try:
            if seconds is None:
                return "-"
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            m = s // 60
            s = s % 60
            return f"{m}m {s}s"
        except Exception:
            return "-"

    def _browse_directory(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(title="Select directory for received files")
        if directory:
            try:
                directory = os.path.abspath(directory)
            except Exception:
                pass
            self.output_dir_var.set(directory)
            # If server is running, update its output directory immediately so
            # newly received files are saved to the selected folder without
            # requiring a server restart.
            try:
                if getattr(self, 'server_running', False) and getattr(self, '_server_instance', None):
                    try:
                        # ensure directory exists
                        os.makedirs(directory, exist_ok=True)
                    except Exception:
                        pass
                    try:
                        self._server_instance.output_dir = Path(directory)
                        self._log_receive(f"Updated server output_dir to: {directory}")
                    except Exception:
                        pass
            except Exception:
                pass

    def _human_readable_age(self, seconds: int) -> str:
        """Return a compact human-readable age for seconds (e.g., '5s', '2m', '1h')."""
        try:
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            m = s // 60
            if m < 60:
                return f"{m}m"
            h = m // 60
            return f"{h}h"
        except Exception:
            return "now"

    def _on_files_dropped(self, event):
        """Handle files dropped onto the files_listbox (tkinterdnd2 provides event.data)."""
        try:
            # event.data may be a Tcl list of file paths; use root.splitlist to parse
            items = self.root.splitlist(event.data)
            added = 0
            for p in items:
                # On Windows paths may come wrapped in { } if they contain spaces
                if p.startswith("{") and p.endswith("}"):
                    p = p[1:-1]
                if os.path.exists(p):
                    self.selected_files.append(p)
                    added += 1
            if added:
                self._update_files_listbox()
                self._log_send(f"Added {added} file(s)/folder(s) via drag-and-drop")
        except Exception as e:
            try:
                self._log_send(f"Drag-and-drop error: {e}")
            except Exception:
                pass

    def _paste_files_from_clipboard(self):
        """Fallback method to paste files from clipboard when DnD is unavailable."""
        try:
            # Get clipboard content and parse file paths (Windows file paths are separated by \r\n)
            clipboard_content = self.root.clipboard_get()
            if not clipboard_content:
                return
            paths = [p.strip() for p in clipboard_content.split('\n') if p.strip()]
            added = 0
            for p in paths:
                # Remove quotes if present (sometimes Windows puts paths in quotes)
                p = p.strip('"')
                if os.path.exists(p):
                    if p not in self.selected_files:
                        self.selected_files.append(p)
                        added += 1
            if added:
                self._update_files_listbox()
                self._log_send(f"Added {added} file(s)/folder(s) via clipboard paste (Ctrl+V)")
            else:
                self._log_send("Clipboard does not contain valid file paths")
        except Exception as e:
            try:
                self._log_send(f"Clipboard paste error: {e}")
            except Exception:
                pass

    def _log_send(self, message):
        """Add message to send log and write to file. `level` default INFO."""
        self.send_log.config(state="normal")
        timestamp_local = time.strftime("%H:%M:%S")
        iso_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.send_log.insert(tk.END, f"[{timestamp_local}] {message}\n")
        self.send_log.see(tk.END)
        self.send_log.config(state="disabled")
        self.status_bar.config(text=f"Send: {message}")
        # Write to log file with ISO timestamp and level
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"[{iso_ts}] [INFO] [SEND] {message}\n")
        except Exception:
            pass

    def _log_receive(self, message):
        """Add message to receive log and write to file. `level` default INFO."""
        self.receive_log.config(state="normal")
        timestamp_local = time.strftime("%H:%M:%S")
        iso_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.receive_log.insert(tk.END, f"[{timestamp_local}] {message}\n")
        self.receive_log.see(tk.END)
        self.receive_log.config(state="disabled")
        self.status_bar.config(text=f"Receive: {message}")
        # Write to log file with ISO timestamp and level
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"[{iso_ts}] [INFO] [RECV] {message}\n")
        except Exception:
            pass

    # -------------------------
    # Sending logic (uses TransferClient)
    # -------------------------
    def _toggle_transfer_pause(self):
        """Toggle pause/resume for ongoing file transfer"""
        try:
            if self.transfer_paused:
                # Resume
                self._pause_event.set()
                self.transfer_paused = False
                self.pause_btn.config(text="⏸ PAUSE")
                self._log_send("[Transfer] Resumed")
            else:
                # Pause
                self._pause_event.clear()
                self.transfer_paused = True
                self.pause_btn.config(text="▶ RESUME")
                self._log_send("[Transfer] Paused")
        except Exception as e:
            self._log_send(f"Pause toggle error: {e}")

    def _send_file(self):
        """Send file(s) or folder in separate thread"""
        host = self.host_entry.get().strip()
        port_str = self.send_port_entry.get().strip()

        # Validation
        if not host:
            messagebox.showerror("Error", "Please enter receiver IP address")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return

        if not self.selected_files:
            messagebox.showerror(
                "Error", "Please select at least one file or folder to send"
            )
            return

        # Verify all files/folders exist
        for filepath in self.selected_files:
            if not os.path.exists(filepath):
                messagebox.showerror("Error", f"Path not found: {filepath}")
                return

        # Disable button during transfer
        self.send_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.send_progress["value"] = 0
        self._log_send(f"Starting transfer to {host}:{port}...")
        self._log_send(f"Files to send: {len(self.selected_files)}")

        # Reset pause state
        self.transfer_paused = False
        self._pause_event.set()
        self.pause_btn.config(text="⏸ PAUSE")

        # Run transfer in thread
        thread = threading.Thread(
            target=self._send_file_thread, args=(host, port, self.selected_files)
        )
        thread.daemon = True
        thread.start()

    def _compress_files_to_zip(self, filepaths):
        """
        Compress files into a ZIP archive.
        Args:
            filepaths: list of file paths to compress
        Returns:
            path to the created ZIP file
        """
        try:
            import tempfile
            # Create temporary ZIP file
            fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='ft_')
            os.close(fd)
            
            zip_path = Path(zip_path)
            self._log_send(f"Compressing {len(filepaths)} file(s) to ZIP...")
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filepath in filepaths:
                    fpath = Path(filepath)
                    if fpath.is_file():
                        # Add file to ZIP with relative name
                        arcname = fpath.name
                        zf.write(fpath, arcname=arcname)
                    elif fpath.is_dir():
                        # Recursively add directory contents
                        for file_in_dir in fpath.rglob('*'):
                            if file_in_dir.is_file():
                                arcname = file_in_dir.relative_to(fpath.parent)
                                zf.write(file_in_dir, arcname=str(arcname).replace('\\', '/'))
            
            zip_size = zip_path.stat().st_size
            self._log_send(f"Compression complete: {self._format_file_size(zip_size)}")
            return str(zip_path)
        except Exception as e:
            self._log_send(f"Compression failed: {e}")
            raise

    def _send_file_thread(self, host, port, filepaths):
        """Thread function to send file(s) with progress callback"""
        success = False
        send_start_time = time.time()
        total_size_sent = 0
        transferred_files = []  # Track files for history
        try:
            client = TransferClient(host, port, pause_event=self._pause_event)
            self._log_send(f"Connecting to {host}:{port}...")

            # Progress callback updates UI
            def progress_callback(
                sent,
                total,
                speed=None,
                eta=None,
                total_sent=None,
                total_size=None,
                total_eta=None,
                filename=None,
            ):
                # Update per-file progress bar
                try:
                    progress = (sent / total) * 100 if total else 0
                except Exception:
                    progress = 0
                self.root.after(0, lambda: self.send_progress.config(value=progress))

                # Update percentage and bytes transferred
                try:
                    percent = int(progress)
                    self.root.after(
                        0, lambda: self.progress_percent_var.set(f"{percent}%")
                    )
                    sent_str = self._format_file_size(sent)
                    total_str = self._format_file_size(total)
                    self.root.after(
                        0,
                        lambda: self.bytes_transferred_var.set(
                            f"{sent_str} / {total_str}"
                        ),
                    )
                except Exception:
                    pass

                # Update speed and ETA labels
                try:
                    if speed is not None:
                        speed_str = self._format_transfer_speed(speed)
                        eta_file_str = self._format_eta(eta)
                        eta_total_str = self._format_eta(total_eta)
                        self.root.after(
                            0, lambda: self.speed_var.set(f"Speed: {speed_str}")
                        )
                        self.root.after(
                            0,
                            lambda: self.eta_file_var.set(f"ETA file: {eta_file_str}"),
                        )
                        self.root.after(
                            0,
                            lambda: self.eta_total_var.set(
                                f"ETA total: {eta_total_str}"
                            ),
                        )
                    else:
                        self.root.after(0, lambda: self.speed_var.set("Speed: -"))
                        self.root.after(0, lambda: self.eta_file_var.set("ETA file: -"))
                        self.root.after(
                            0, lambda: self.eta_total_var.set("ETA total: -")
                        )
                except Exception:
                    pass

            # Send files
            if len(filepaths) == 1 and os.path.isfile(filepaths[0]):
                # Single file
                fname = Path(filepaths[0]).name
                
                # Optional compression: if enabled and multiple files or large file, compress
                files_to_send = filepaths
                if self.compress_before_send:
                    try:
                        compressed_path = self._compress_files_to_zip(filepaths)
                        files_to_send = [compressed_path]
                        fname = Path(compressed_path).name
                    except Exception as e:
                        self._log_send(f"Warning: compression failed, sending uncompressed: {e}")
                
                self._log_send(f"Sending file: {fname} (resumable)")
                try:
                    # update UI indicator: sending
                    self.root.after(
                        0,
                        lambda: self.resumable_status_var.set("Resumable: Sending..."),
                    )
                    result = client.send_single_file(
                        files_to_send[0], progress_callback=progress_callback
                    )
                    if isinstance(result, tuple):
                        offset, ok = result
                        if offset and offset > 0:
                            self.root.after(
                                0,
                                lambda off=offset: self._log_send(
                                    f"Resumed from offset: {off} bytes"
                                ),
                            )
                            self.root.after(
                                0,
                                lambda off=offset: self.resumable_status_var.set(
                                    f"Resumed: {off} bytes"
                                ),
                            )
                        else:
                            self.root.after(
                                0,
                                lambda: self.resumable_status_var.set(
                                    "Resumable: Sent (fresh)"
                                ),
                            )
                        self.root.after(
                            0, lambda: self._log_send("File sent successfully!")
                        )
                        # Track file for history
                        try:
                            fpath = Path(filepaths[0])
                            if fpath.exists():
                                total_size_sent += fpath.stat().st_size
                                transferred_files.append(fname)
                        except Exception:
                            pass
                    else:
                        # backward compatibility: no tuple returned
                        self.root.after(
                            0,
                            lambda: self.resumable_status_var.set(
                                "Resumable: Sent (unknown)"
                            ),
                        )
                        self.root.after(
                            0, lambda: self._log_send("File sent successfully!")
                        )
                        # Track file for history
                        try:
                            fpath = Path(filepaths[0])
                            if fpath.exists():
                                total_size_sent += fpath.stat().st_size
                                transferred_files.append(fname)
                        except Exception:
                            pass
                except Exception as e:
                    self.root.after(0, lambda: self._log_send(f"Error: {e}"))
                    self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
                    self.root.after(
                        0, lambda: self.resumable_status_var.set("Resumable: Error")
                    )
                finally:
                    # reset indicator after short delay
                    try:
                        self.root.after(
                            3000,
                            lambda: self.resumable_status_var.set("Resumable: Off"),
                        )
                    except Exception:
                        pass
            elif len(filepaths) == 1 and os.path.isdir(filepaths[0]):
                # Single directory
                self._log_send(f"Sending directory: {Path(filepaths[0]).name}")
                client.send_directory(filepaths[0], progress_callback=progress_callback)
                self.root.after(
                    0, lambda: self._log_send("Directory sent successfully!")
                )
                # Track directory for history
                try:
                    dir_path = Path(filepaths[0])
                    dir_size = sum(f.stat().st_size for f in dir_path.rglob('*') if f.is_file())
                    total_size_sent += dir_size
                    transferred_files.append(dir_path.name)
                except Exception:
                    pass
            else:
                # Multiple files/folders
                self._log_send(f"Sending {len(filepaths)} item(s)...")
                
                # Optional compression: if enabled, create ZIP
                files_to_send = filepaths
                if self.compress_before_send:
                    try:
                        compressed_path = self._compress_files_to_zip(filepaths)
                        files_to_send = [compressed_path]
                        self._log_send("Sending compressed archive...")
                    except Exception as e:
                        self._log_send(f"Warning: compression failed, sending uncompressed: {e}")
                        files_to_send = filepaths
                
                # Expand directories to files
                all_files = []
                for filepath in files_to_send:
                    if os.path.isdir(filepath):
                        path = Path(filepath)
                        all_files.extend(path.rglob("*"))
                    else:
                        all_files.append(Path(filepath))

                files_only = [f for f in all_files if f.is_file()]
                if files_only:
                    client.send_multiple_files(
                        files_only, progress_callback=progress_callback
                    )
                    self.root.after(
                        0,
                        lambda: self._log_send(
                            f"All {len(files_only)} file(s) sent successfully!"
                        ),
                    )
                    # Track files for history
                    try:
                        for fpath in files_only:
                            total_size_sent += fpath.stat().st_size
                            transferred_files.append(fpath.name)
                    except Exception:
                        pass

            self.root.after(0, lambda: self.send_progress.config(value=100))

            # mark overall success if we reached here without raising
            success = True
            
            # Record transfer history
            try:
                duration = time.time() - send_start_time
                if transferred_files and total_size_sent > 0:
                    filename_display = transferred_files[0] if len(transferred_files) == 1 else f"{len(transferred_files)} files"
                    self._add_transfer_history('send', filename_display, total_size_sent, duration)
            except Exception as e:
                self._log_send(f"Warning: Failed to record transfer history: {e}")

        except Exception as e:
            self.root.after(0, lambda: self._log_send(f"Error: {e}"))
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            # Clean up temporary ZIP files if compression was used
            if self.compress_before_send:
                try:
                    import tempfile
                    # Try to remove any temp files created during compression
                    temp_dir = Path(tempfile.gettempdir())
                    for zip_file in temp_dir.glob('ft_*.zip'):
                        try:
                            if zip_file.exists():
                                zip_file.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
            
            self.root.after(0, lambda: self.send_btn.config(state="normal"))
            # If send succeeded, clear the selected files list and update UI
            try:
                if success:
                    # clear selection in main thread after a short delay so UI reflects final state
                    self.root.after(500, lambda: (self.selected_files.clear(), self._update_files_listbox(), self._log_send("Send list cleared after successful send")))
            except Exception:
                pass

    # -------------------------
    # Server (receiver) logic
    # -------------------------
    def _start_server(self):
        """Start the receiver server"""
        port_str = self.receive_port_entry.get().strip()
        output_dir = self.output_dir_var.get()
        try:
            output_dir = os.path.abspath(output_dir)
        except Exception:
            pass
        machine_name = self.machine_name_entry.get().strip() or socket.gethostname()

        if not machine_name:
            messagebox.showerror("Error", "Please enter a machine name")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return

        # Create output directory if it doesn't exist (ensure absolute path)
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            pass

        self.machine_name = machine_name
        self.server_running = True
        self.start_server_btn.config(state="disabled")
        self.stop_server_btn.config(state="normal")
        self.machine_name_entry.config(state="readonly")
        self.receive_port_entry.config(state="readonly")
        self.server_status_label.config(text="Status: Running", foreground="green")
        try:
            self.server_status_icon.config(foreground="green")
        except Exception:
            pass

        self._log_receive(f"Starting server on port {port}...")
        self._log_receive(f"Saving files to: {output_dir}")

        # If discovery exists and the port changed, restart discovery with new port
        try:
            if self.discovery:
                current_port = getattr(self.discovery, "port", None)
                if current_port != port:
                    self._start_discovery(socket.gethostname(), port)
            else:
                # start discovery if somehow missing
                self._start_discovery(socket.gethostname(), port)
        except Exception as e:
            self._log_receive(f"Service discovery error: {e}")

        # Start server in separate thread
        self.server_thread = threading.Thread(
            target=self._run_server, args=(port, output_dir)
        )
        self.server_thread.daemon = True
        self.server_thread.start()
        # Start connection monitor: warn if server listens but receives no connections
        try:
            self.last_connection_time = None
            self._no_conn_warned = False
            # schedule first check in 10 seconds
            self._schedule_connection_check()
        except Exception:
            pass
        # record server start time
        try:
            self.server_start_time = time.time()
        except Exception:
            self.server_start_time = None

    def _stop_server(self):
        """Stop the receiver server"""
        self.server_running = False
        self.start_server_btn.config(state="normal")
        self.stop_server_btn.config(state="disabled")
        self.machine_name_entry.config(state="normal")
        self.receive_port_entry.config(state="normal")
        self.server_status_label.config(text="Status: Stopped", foreground="red")
        try:
            self.server_status_icon.config(foreground="red")
        except Exception:
            pass
        self._log_receive("Server stopped")

        # If discovery exists, re-broadcast current receive_port value (in case user changed it)
        try:
            if self.discovery:
                try:
                    new_port = int(self.receive_port_entry.get().strip())
                except Exception:
                    new_port = getattr(self.discovery, "port", 5000)
                # restart discovery to broadcast selected port
                self._start_discovery(socket.gethostname(), new_port)
        except Exception:
            pass
        # Cancel connection monitor if running
        try:
            if self._connection_check_after_id:
                self.root.after_cancel(self._connection_check_after_id)
                self._connection_check_after_id = None
        except Exception:
            pass
        try:
            self.server_start_time = None
        except Exception:
            pass
        # Clear stored server instance reference
        try:
            self._server_instance = None
        except Exception:
            pass

    def _run_server(self, port, output_dir):
        """Run server in thread"""
        try:
            # Progress callback from server to update Receive tab UI
            def _server_progress(sent, total, speed=None, eta=None, filename=None):
                try:
                    progress = (sent / total) * 100 if total else 0
                except Exception:
                    progress = 0
                try:
                    # Update progress bar and text in the main thread
                    self.root.after(0, lambda: self.recv_progress.config(value=progress))
                    percent = int(progress)
                    self.root.after(0, lambda: self.recv_progress_percent_var.set(f"{percent}%"))
                    sent_str = self._format_file_size(sent)
                    total_str = self._format_file_size(total)
                    self.root.after(0, lambda: self.recv_bytes_var.set(f"{sent_str} / {total_str}"))
                    if speed is not None:
                        speed_str = self._format_transfer_speed(speed)
                        self.root.after(0, lambda: self.recv_speed_var.set(f"Speed: {speed_str}"))
                    else:
                        self.root.after(0, lambda: self.recv_speed_var.set("Speed: -"))
                    self.root.after(0, lambda: self.recv_eta_var.set(f"ETA: {self._format_eta(eta)}"))
                except Exception:
                    pass

            # Log initialization to help diagnose receive issues
            try:
                self._log_receive(f"Initializing TransferServer on port {port}, output_dir={output_dir}")
            except Exception:
                pass
            server = TransferServer(port=port, output_dir=output_dir, progress_callback=_server_progress)
            # Keep a reference to the running server so the GUI can update its
            # output directory while it's running (user may change Save folder).
            try:
                self._server_instance = server
            except Exception:
                self._server_instance = None

            original_receive_files = server._receive_files

            def gui_receive_files(conn):
                try:
                    peer_addr = conn.getpeername()
                    recv_start_time = time.time()
                    total_received_size = 0
                    received_files = []
                    # mark that we just received a connection
                    try:
                        self.last_connection_time = time.time()
                        self._no_conn_warned = False
                        # restore server status visual indicator
                        self.root.after(
                            0,
                            lambda: self.server_status_label.config(
                                text="Status: Running", foreground="green"
                            ),
                        )
                        try:
                            self.root.after(
                                0,
                                lambda: self.server_status_icon.config(
                                    foreground="green"
                                ),
                            )
                        except Exception:
                            pass
                    except Exception:
                        pass
                    self.root.after(
                        0,
                        lambda: self._log_receive(
                            f"Connection from {peer_addr[0]}:{peer_addr[1]}"
                        ),
                    )
                    result = original_receive_files(conn)
                    if result:
                        # result may be a list (multi-file) or a tuple (filename, filesize)
                        if isinstance(result, list) and result:
                            # Log each received file
                            for item in result:
                                try:
                                    fname, fsize = item
                                    total_received_size += fsize
                                    received_files.append(fname)
                                    self.root.after(
                                        0,
                                        lambda fn=fname, fs=fsize: self._log_receive(
                                            f"Received: {fn} ({fs} bytes)"
                                        ),
                                    )
                                    # Add to recent files list
                                    # Compute full path based on server's output_dir (capture now)
                                    try:
                                        fullp = os.path.join(str(server.output_dir), fname)
                                    except Exception:
                                        fullp = fname
                                    self.root.after(
                                        0,
                                        lambda fp=fullp, fs=fsize: self._add_recent_file(fp, fs),
                                    )
                                except Exception:
                                    pass
                        elif isinstance(result, tuple) and len(result) >= 2:
                            fname, fsize = result[0], result[1]
                            total_received_size = fsize
                            received_files.append(fname)
                            self.root.after(
                                0,
                                lambda: self._log_receive(
                                    f"Received: {fname} ({fsize} bytes)"
                                ),
                            )
                            try:
                                fullp = os.path.join(str(server.output_dir), fname)
                            except Exception:
                                fullp = fname
                            self.root.after(0, lambda fp=fullp, fs=fsize: self._add_recent_file(fp, fs))
                            # Trigger notification
                            self.root.after(0, lambda fn=fname: self._notify_file_received(fn))
                        
                        # Record transfer history for received files
                        try:
                            duration = time.time() - recv_start_time
                            if received_files and total_received_size > 0:
                                filename_display = received_files[0] if len(received_files) == 1 else f"{len(received_files)} files"
                                self._add_transfer_history('recv', filename_display, total_received_size, duration)
                        except Exception as e:
                            self.root.after(0, lambda: self._log_receive(f"Warning: Failed to record transfer history: {e}"))
                        
                        # after receiving, refresh discovery list (in case peers changed)
                        self.root.after(0, self._update_machines_list)
                        # Update tab badge
                        self.root.after(0, self._update_tab_badge)
                        return result
                except Exception as e:
                    self.root.after(
                        0, lambda: self._log_receive(f"Error receiving file: {e}")
                    )
                return None

            # Replace method and start server (blocking)
            server._receive_files = gui_receive_files
            server.start()

        except Exception as e:
            self.root.after(0, lambda: self._log_receive(f"Server error: {e}"))
            self.root.after(0, lambda: messagebox.showerror("Server Error", str(e)))
        finally:
            # Clear server instance reference and ensure UI updated as stopped when server loop exits
            try:
                self._server_instance = None
            except Exception:
                pass
            self.root.after(0, self._stop_server)

    # -------------------------
    # Partial files cleanup
    # -------------------------
    def _cleanup_partial_files_dialog(self):
        """Ask user to confirm cleanup of partial files and perform cleanup."""
        try:
            days = getattr(self, "partial_cleanup_days", 30)
            prompt = f"Delete '.partial' files older than {days} days in the configured Save folder?"
            if not messagebox.askyesno("Clean Partial Files", prompt):
                return
            # perform cleanup
            deleted = self._cleanup_partial_files(days=days)
            messagebox.showinfo(
                "Cleanup Complete", f"Deleted {deleted} partial file(s)"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Cleanup failed: {e}")

    def _cleanup_partial_files(self, days: int = 30):
        """Remove .partial files older than `days` from the configured output directory.

        Returns the number of deleted files.
        """
        try:
            out_dir = (
                self.output_dir_var.get()
                if hasattr(self, "output_dir_var")
                else os.path.join(os.getcwd(), "ReceivedFiles")
            )
            p = Path(out_dir)
            if not p.exists():
                return 0
            cutoff = time.time() - (days * 86400)
            deleted = 0
            for f in p.rglob("*.partial"):
                try:
                    mtime = f.stat().st_mtime
                    if mtime < cutoff:
                        f.unlink()
                        deleted += 1
                except Exception:
                    pass
            return deleted
        except Exception:
            return 0

    def _on_recent_double_click(self, event):
        """Open containing folder and select the recently received file."""
        try:
            sel = self.recent_files_listbox.curselection()
            if not sel:
                return
            index = sel[0]
            entry = self.recent_received_files[index]
            fullpath = entry.get("path") if isinstance(entry, dict) else None
            if not fullpath:
                return
            # Normalize path and open the containing folder, selecting the file when possible.
            try:
                fullpath = os.path.abspath(fullpath)
                folder = os.path.dirname(fullpath)

                if sys.platform.startswith("win"):
                    # If file exists, request Explorer to select it using a single argument
                    # e.g. explorer "/select,C:\path\to\file.txt"
                    if os.path.exists(fullpath):
                        try:
                            subprocess.Popen(["explorer", f"/select,{fullpath}"])
                        except Exception:
                            # Fallback: open containing folder
                            try:
                                os.startfile(folder)
                            except Exception:
                                pass
                    else:
                        # If file missing, open the folder if it exists
                        if os.path.isdir(folder):
                            try:
                                os.startfile(folder)
                            except Exception:
                                pass
                        else:
                            # As last resort, open user's home folder
                            try:
                                os.startfile(os.path.expanduser("~"))
                            except Exception:
                                pass

                elif sys.platform == "darwin":
                    # macOS: use 'open -R' to reveal the file, or open the folder
                    if os.path.exists(fullpath):
                        try:
                            subprocess.Popen(["open", "-R", fullpath])
                        except Exception:
                            try:
                                subprocess.Popen(["open", folder])
                            except Exception:
                                pass
                    else:
                        try:
                            subprocess.Popen(["open", folder])
                        except Exception:
                            pass

                else:
                    # Linux/other: no reliable cross-distro 'select' behaviour; open folder
                    try:
                        subprocess.Popen(["xdg-open", folder])
                    except Exception:
                        try:
                            # fallback using generic open
                            subprocess.Popen(["open", folder])
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    # -------------------------
    # Connection monitor (server health)
    # -------------------------
    def _schedule_connection_check(self, interval_ms: int = 10000):
        """Schedule periodic checks for incoming connections."""
        try:
            # Cancel existing if present
            if self._connection_check_after_id:
                try:
                    self.root.after_cancel(self._connection_check_after_id)
                except Exception:
                    pass
            self._connection_check_after_id = self.root.after(
                interval_ms, self._connection_check
            )
        except Exception:
            self._connection_check_after_id = None

    def _connection_check(self):
        """Check whether server is running and has received any connections recently.

        If server is running, peers exist (discovered), but no connections have
        been received within the threshold, warn the user (likely firewall).
        """
        try:
            # Only run when server is reported running
            if not getattr(self, "server_running", False):
                self._connection_check_after_id = None
                return

            threshold_seconds = 60
            now = time.time()
            # If discovery found peers, we expect possible incoming connections
            peers = self.discovery.get_peers() if self.discovery else {}

            # Only warn if server has been running for at least threshold_seconds
            if (
                self.server_start_time is None
                or (now - self.server_start_time) < threshold_seconds
            ):
                # server hasn't been up long enough to consider this a problem
                self._schedule_connection_check()
                return

            no_recent = (self.last_connection_time is None) or (
                now - self.last_connection_time > threshold_seconds
            )
            if peers and no_recent and not self._no_conn_warned:
                msg = (
                    "Server is listening but hasn't received incoming connections "
                    f"for {threshold_seconds} seconds while peers are present. "
                    "This might indicate a firewall or network issue."
                )
                # Log and show a single warning dialog
                try:
                    self._log_receive(f"[Warning] {msg}")
                    # update visual indicator on server status (no popup)
                    try:
                        self.root.after(
                            0,
                            lambda: self.server_status_label.config(
                                text="Status: Running (No incoming connections)",
                                foreground="orange",
                            ),
                        )
                        self.root.after(
                            0,
                            lambda: self.server_status_icon.config(foreground="orange"),
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
                self._no_conn_warned = True

            # schedule next check
            self._schedule_connection_check()
        except Exception:
            # attempt to reschedule regardless
            try:
                self._schedule_connection_check()
            except Exception:
                pass

    # -------------------------
    # Network utils
    # -------------------------
    def _get_local_ip(self):
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    # -------------------------
    # Config persistence
    # -------------------------
    def _load_config(self):
        """Load GUI config (currently only 'broadcast_only')."""
        if not self._config_path.exists():
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bo = data.get("broadcast_only")
            if isinstance(bo, bool):
                try:
                    self.broadcast_only_var.set(bo)
                except Exception:
                    pass
            # Partial cleanup config
            pcd = data.get("partial_cleanup_days")
            if isinstance(pcd, int):
                try:
                    self.partial_cleanup_days = int(pcd)
                except Exception:
                    self.partial_cleanup_days = 30
            else:
                self.partial_cleanup_days = 30
            auto = data.get("auto_cleanup_partial")
            self.auto_cleanup_partial = bool(auto) if auto is not None else False
            # Show peer details preference
            spd = data.get("show_peer_details")
            if isinstance(spd, bool):
                try:
                    self.show_peer_details = bool(spd)
                except Exception:
                    self.show_peer_details = False
            else:
                self.show_peer_details = False
            # Show peer details preference handled above
            # NERV mode state
            nerv_mode = data.get("nerv_mode")
            if isinstance(nerv_mode, bool) and nerv_mode:
                try:
                    self._nerv_mode = True
                    # Show MAGI tab and activate NERV display
                    self.root.after(1000, self._restore_nerv_mode_on_startup)
                except Exception:
                    pass
            # Receive port (apply to entry)
            try:
                rp = data.get("receive_port")
                if rp is not None:
                    try:
                        self.receive_port_entry.delete(0, tk.END)
                        self.receive_port_entry.insert(0, str(rp))
                    except Exception:
                        pass
            except Exception:
                pass

            # Output directory
            try:
                od = data.get("output_dir")
                if isinstance(od, str) and od:
                    try:
                        self.output_dir_var.set(od)
                    except Exception:
                        pass
            except Exception:
                pass

            # Machine name
            try:
                mn = data.get("machine_name")
                if isinstance(mn, str) and mn:
                    try:
                        self.machine_name_entry.delete(0, tk.END)
                        self.machine_name_entry.insert(0, mn)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

    def _write_config(self):
        """Write GUI config (currently only 'broadcast_only')."""
        data = {"broadcast_only": bool(self.broadcast_only_var.get())}
        try:
            data["partial_cleanup_days"] = int(
                getattr(self, "partial_cleanup_days", 30)
            )
        except Exception:
            data["partial_cleanup_days"] = 30
        try:
            data["auto_cleanup_partial"] = bool(
                getattr(self, "auto_cleanup_partial", False)
            )
        except Exception:
            data["auto_cleanup_partial"] = False
        try:
            data["show_peer_details"] = bool(getattr(self, "show_peer_details", False))
        except Exception:
            data["show_peer_details"] = False
        # Persist receive port, output directory and machine name
        try:
            data["receive_port"] = self.receive_port_entry.get().strip()
        except Exception:
            data["receive_port"] = "5000"
        try:
            try:
                data["output_dir"] = os.path.abspath(self.output_dir_var.get())
            except Exception:
                data["output_dir"] = self.output_dir_var.get()
        except Exception:
            data["output_dir"] = os.path.join(os.getcwd(), "ReceivedFiles")
        try:
            data["machine_name"] = self.machine_name_entry.get().strip()
        except Exception:
            data["machine_name"] = socket.gethostname()
        # Save NERV mode state
        try:
            data["nerv_mode"] = bool(getattr(self, "_nerv_mode", False))
        except Exception:
            data["nerv_mode"] = False
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            # Attempt to log the error to the GUI log file so user can diagnose
            try:
                with open(self._log_file_path, 'a', encoding='utf-8') as lf:
                    lf.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] [ERROR] [CONFIG] Failed writing config: {e}\n")
            except Exception:
                pass

    # -------------------------
    # Main / cleanup
    # -------------------------


def main():
    # Prefer the Tk wrapper from tkinterdnd2 if available so DnD works.
    if TKDND_AVAILABLE and TkinterDnD:
        root = TkinterDnD()
    else:
        root = tk.Tk()
    app = FileTransferGUI(root)

    def _on_closing_request():
        # If tray is available, hide to tray instead of exiting.
        if TRAY_AVAILABLE:
            try:
                app._hide_to_tray()
                return
            except Exception:
                pass

        # Otherwise perform full cleanup and exit
        try:
            if app.server_running:
                app._stop_server()
        except Exception:
            pass
        try:
            if app.discovery:
                app.discovery.stop()
        except Exception:
            pass
        try:
            app._write_config()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", _on_closing_request)
    root.mainloop()


if __name__ == "__main__":
    main()
