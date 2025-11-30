#!/usr/bin/env python3
"""
GUI File Transfer Application
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
from pathlib import Path
from transfer_server import TransferServer
from transfer_client import TransferClient
from service_discovery import ServiceDiscovery

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
        self.root.title("File Transfer Application")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

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
        self.show_peer_details = True

        # Selected files to send
        self.selected_files = []

        # Config file path (stored next to this script)
        try:
            self._config_path = Path(__file__).parent / "ft_gui_config.json"
        except Exception:
            self._config_path = Path("ft_gui_config.json")

        # Load saved preferences (if any)
        try:
            self._load_config()
        except Exception:
            pass

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Create tabs
        self.send_frame = ttk.Frame(self.notebook)
        self.receive_frame = ttk.Frame(self.notebook)
        self.about_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.send_frame, text="Send Files")
        self.notebook.add(self.receive_frame, text="Receive Files")
        self.notebook.add(self.about_frame, text="About")

        self._create_send_tab()
        self._create_receive_tab()
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

        # Start discovery after UI is ready
        self.root.after(1000, self.start_discovery_service)

        # Start periodic polling to update machines list (every 1.5 seconds)
        self._schedule_discovery_poll()

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
        except Exception:
            pass

        # Schedule next poll
        self.root.after(1500, self._schedule_discovery_poll)

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

            # Reset broadcast-only preference
            try:
                self.broadcast_only_var.set(True)
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
        details_chk_var = tk.BooleanVar(value=getattr(self, "show_peer_details", True))
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
                self.show_peer_details = True

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

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", padx=5, pady=5)

        add_file_btn = ttk.Button(
            btn_frame, text="📄 Add File(s)", command=self._browse_files_multiple
        )
        add_file_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(add_file_btn, "Select one or more files to send")

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

        send_row = ttk.Frame(right_frame)
        # Match horizontal padding with other control rows for visual alignment
        send_row.pack(pady=10, fill="x", padx=5)

        self.send_btn = ttk.Button(
            send_row, text="▶ SEND FILES", command=self._send_file
        )
        self.send_btn.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(self.send_btn, "Start file transfer to selected receiver")

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

        # Track recently received files
        self.recent_received_files = []

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
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Application header - centered
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill="x", pady=(0, 20), padx=20, anchor="center")

        # Application title with larger font
        title_label = ttk.Label(
            header_frame,
            text="File Transfer Application",
            font=("Arial", 16, "bold"),
            foreground="#2c3e50",
        )
        title_label.pack(pady=(0, 10), anchor="center")

        # Version info with beta badge
        version_frame = ttk.Frame(header_frame)
        version_frame.pack(anchor="center")

        version_label = ttk.Label(
            version_frame, text="Version 0.1.3", font=("Arial", 12, "bold")
        )
        version_label.pack(side=tk.LEFT, padx=(0, 10))

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

        # Separator
        ttk.Separator(scrollable_frame, orient="horizontal").pack(
            fill="x", pady=20, padx=20
        )

        # Features section
        features_frame = ttk.LabelFrame(scrollable_frame, text="Features")
        features_frame.pack(fill="x", pady=(0, 20), padx=20, anchor="center")

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
        author_frame = ttk.LabelFrame(scrollable_frame, text="Developer Information")
        author_frame.pack(fill="x", pady=(0, 20), padx=20, anchor="center")

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
        contact_frame = ttk.LabelFrame(scrollable_frame, text="Contact & Support")
        contact_frame.pack(fill="x", pady=(0, 20), padx=20, anchor="center")

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
            display = f"{filename} ({size_str})"

            # Keep only last 20 files
            if len(self.recent_received_files) >= 20:
                self.recent_files_listbox.delete(0, 0)
                self.recent_received_files.pop(0)

            self.recent_received_files.append(display)
            self.recent_files_listbox.insert(tk.END, display)
            self.recent_files_listbox.see(tk.END)
        except Exception:
            pass

    def _update_tab_badge(self):
        """Update badge on Receive Files tab when files arrive."""
        try:
            if self.recent_received_files:
                self.notebook.tab(1, text=f"Receive Files 🔔")
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
            self.start_discovery_service()
            self.root.after(2000, self._update_machines_list)
        else:
            # Discovery exists, force update
            self._update_machines_list()

        self._log_send(
            "Scan complete. Found "
            + str(len(self.discovery.get_peers() if self.discovery else {}))
            + " machines."
        )

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
                # Update selected receiver label with green highlight
                self.selected_receiver_var.set(
                    f"🟢 {machine_name}\n({peer_info['ip']}:{peer_info['port']})"
                )
                self.selected_receiver_label.config(foreground="darkgreen")

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

            # Determine status indicator
            if last_seen_ts:
                age = int(now - float(last_seen_ts))
                if age < 5:
                    status_icon = "🟢"  # Online
                elif age < 30:
                    status_icon = "🟡"  # Recently seen
                else:
                    status_icon = "⚫"  # Offline/stale
                age_str = self._human_readable_age(age)
            else:
                status_icon = "🔵"
                age_str = "now"

            if getattr(self, "show_peer_details", True):
                display_name = f"{status_icon} {name} ({ip}:{port}) [{age_str}]"
            else:
                display_name = f"{status_icon} {name}"

            # Insert into treeview
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
            self.output_dir_var.set(directory)

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

    def _log_send(self, message):
        """Add message to send log"""
        self.send_log.config(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.send_log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.send_log.see(tk.END)
        self.send_log.config(state="disabled")
        self.status_bar.config(text=f"Send: {message}")

    def _log_receive(self, message):
        """Add message to receive log"""
        self.receive_log.config(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.receive_log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.receive_log.see(tk.END)
        self.receive_log.config(state="disabled")
        self.status_bar.config(text=f"Receive: {message}")

    # -------------------------
    # Sending logic (uses TransferClient)
    # -------------------------
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
        self.send_progress["value"] = 0
        self._log_send(f"Starting transfer to {host}:{port}...")
        self._log_send(f"Files to send: {len(self.selected_files)}")

        # Run transfer in thread
        thread = threading.Thread(
            target=self._send_file_thread, args=(host, port, self.selected_files)
        )
        thread.daemon = True
        thread.start()

    def _send_file_thread(self, host, port, filepaths):
        """Thread function to send file(s) with progress callback"""
        try:
            client = TransferClient(host, port)
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
                self._log_send(f"Sending file: {fname} (resumable)")
                try:
                    # update UI indicator: sending
                    self.root.after(
                        0,
                        lambda: self.resumable_status_var.set("Resumable: Sending..."),
                    )
                    result = client.send_single_file(
                        filepaths[0], progress_callback=progress_callback
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
            else:
                # Multiple files/folders
                self._log_send(f"Sending {len(filepaths)} item(s)...")
                # Expand directories to files
                all_files = []
                for filepath in filepaths:
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

            self.root.after(0, lambda: self.send_progress.config(value=100))

        except Exception as e:
            self.root.after(0, lambda: self._log_send(f"Error: {e}"))
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.root.after(0, lambda: self.send_btn.config(state="normal"))

    # -------------------------
    # Server (receiver) logic
    # -------------------------
    def _start_server(self):
        """Start the receiver server"""
        port_str = self.receive_port_entry.get().strip()
        output_dir = self.output_dir_var.get()
        machine_name = self.machine_name_entry.get().strip() or socket.gethostname()

        if not machine_name:
            messagebox.showerror("Error", "Please enter a machine name")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

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
        # The TransferServer class provided is blocking and returns after a single transfer.
        # We set server_running False so UI knows it's stopped; actual thread will exit when server returns.
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

    def _run_server(self, port, output_dir):
        """Run server in thread"""
        try:
            server = TransferServer(port=port, output_dir=output_dir)

            # Wrap server._receive_files to log into GUI
            # NOTE: TransferServer.start calls _receive_files(conn) directly,
            # so we must wrap that method (not _receive_file) to intercept
            # incoming transfers and show them in the Receive log.
            original_receive_files = server._receive_files

            def gui_receive_files(conn):
                try:
                    peer_addr = conn.getpeername()
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
                                    self.root.after(
                                        0,
                                        lambda fn=fname, fs=fsize: self._log_receive(
                                            f"Received: {fn} ({fs} bytes)"
                                        ),
                                    )
                                    # Add to recent files list
                                    self.root.after(
                                        0,
                                        lambda fn=fname, fs=fsize: self._add_recent_file(
                                            fn, fs
                                        ),
                                    )
                                except Exception:
                                    pass
                        elif isinstance(result, tuple) and len(result) >= 2:
                            fname, fsize = result[0], result[1]
                            self.root.after(
                                0,
                                lambda: self._log_receive(
                                    f"Received: {fname} ({fsize} bytes)"
                                ),
                            )
                            self.root.after(
                                0,
                                lambda fn=fname, fs=fsize: self._add_recent_file(
                                    fn, fs
                                ),
                            )
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
            # Ensure UI updated as stopped when server loop exits
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
                    self.show_peer_details = True
            else:
                self.show_peer_details = True
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
            data["show_peer_details"] = bool(getattr(self, "show_peer_details", True))
        except Exception:
            data["show_peer_details"] = True
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
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
