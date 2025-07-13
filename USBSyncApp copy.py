import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import subprocess
import time
import os
import psutil
import winsound
import threading
import queue

# Constants
POLL_INTERVAL = 5  # seconds
DEST_FOLDER_NAME = ""  # Empty string means copy to USB root

# Determine the script's directory for robust path handling and define a single log file path.
try:
    # This works when running as a script.
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Fallback for environments where __file__ is not defined (e.g., some IDEs, frozen apps).
    SCRIPT_DIR = os.getcwd()

LOG_FILE_PATH = os.path.join(SCRIPT_DIR, "usbsync.log")

class USBSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("USB Sync Tool")
        self.root.geometry("650x400")
        self.sync_enabled = tk.BooleanVar(value=False)
        self.source_folder = tk.StringVar()
        self.drive_status = {}
        self.drive_threads = {}

        # Thread-safe communication
        self.ui_queue = queue.Queue()
        self.status_lock = threading.Lock()

        self.setup_ui()
        # Start the background polling thread
        self.sync_enabled.trace_add("write", self._on_sync_toggled)
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.process_queue()

    def setup_ui(self):
        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10)

        tk.Button(frame_top, text="Select Source Folder", command=self.select_source).pack(side=tk.LEFT)
        tk.Label(frame_top, textvariable=self.source_folder, width=50, anchor="w").pack(side=tk.LEFT, padx=10)

        frame_toggle = tk.Frame(self.root)
        frame_toggle.pack(pady=5)
        tk.Checkbutton(frame_toggle, text="Enable Sync", variable=self.sync_enabled).pack()

        # Drive list table
        self.tree = ttk.Treeview(self.root, columns=("Drive", "Status", "Progress"), show="headings", height=10)
        self.tree.heading("Drive", text="Drive")
        self.tree.heading("Status", text="Status")
        self.tree.heading("Progress", text="Progress")
        self.tree.column("Drive", width=100, anchor="w")
        self.tree.column("Status", width=200, anchor="w")
        self.tree.column("Progress", width=100, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def select_source(self):
        folder = filedialog.askdirectory()
        if folder:
            self.source_folder.set(folder)

    def process_queue(self):
        """Process messages from the queue to safely update the UI."""
        try:
            while not self.ui_queue.empty():
                message = self.ui_queue.get_nowait()
                msg_type, data = message

                if msg_type == "update":
                    drive, status, progress = data
                    if self.tree.exists(drive):
                        self.tree.item(drive, values=(drive, status, progress))
                
                elif msg_type == "drive_added":
                    drive = data
                    # Always add the drive to the UI if it's not already there.
                    if not self.tree.exists(drive):
                        self.tree.insert("", "end", iid=drive, values=(drive, "Ready", "0%"))
                        with self.status_lock:
                            self.drive_status[drive] = {"status": "Ready", "progress": "0%"}

                    # If sync is enabled, immediately try to start the sync process.
                    if self.sync_enabled.get() and self.source_folder.get():
                        self._start_sync_if_ready(drive)

                elif msg_type == "drive_removed":
                    drive = data
                    if self.tree.exists(drive):
                        self.tree.delete(drive)
                    
                    with self.status_lock:
                        if drive in self.drive_status:
                            del self.drive_status[drive]
                        if drive in self.drive_threads:
                            del self.drive_threads[drive]
                
                elif msg_type == "trigger_sync_all":
                    # Called when 'Enable Sync' is checked. Iterate through all visible drives.
                    if self.sync_enabled.get() and self.source_folder.get():
                        for drive_id in self.tree.get_children():
                            self._start_sync_if_ready(drive_id)

        finally:
            # Schedule the next check
            self.root.after(100, self.process_queue)

    def _poll_loop(self):
        known_drives = set()
        while True:
            try:
                current_drives = set(self.get_removable_drives())
                
                # --- Handle new drives ---
                new_drives = current_drives - known_drives
                for drive in new_drives:
                    self.ui_queue.put(("drive_added", drive))

                # --- Handle removed drives ---
                removed_drives = known_drives - current_drives
                for drive in removed_drives:
                    self.ui_queue.put(("drive_removed", drive))

                known_drives = current_drives
            except Exception as e:
                print(f"Error in drive polling loop: {e}")
            finally:
                time.sleep(POLL_INTERVAL)

    def _on_sync_toggled(self, *args):
        """Callback when the 'Enable Sync' checkbox is changed."""
        if self.sync_enabled.get():
            self.ui_queue.put(("trigger_sync_all", None))

    def get_removable_drives(self):
        return [p.device for p in psutil.disk_partitions(all=False) if 'removable' in p.opts.lower()]

    def _update_status(self, drive, status, progress):
        """Helper to update shared status dict and push to UI queue."""
        with self.status_lock:
            if drive in self.drive_status:
                self.drive_status[drive]["status"] = status
                self.drive_status[drive]["progress"] = progress
        self.ui_queue.put(("update", (drive, status, progress)))

    def _start_sync_if_ready(self, drive):
        """Checks a drive's status and starts a sync thread if it's 'Ready'."""
        with self.status_lock:
            current_status = self.drive_status.get(drive, {}).get("status")

        if current_status == "Ready":
            src_folder = self.source_folder.get()
            thread = threading.Thread(target=self.sync_to_drive, args=(drive, src_folder), daemon=True)
            self.drive_threads[drive] = thread
            thread.start()

    def sync_to_drive(self, drive, src):
        self._update_status(drive, "Syncing", "0%")
        dest = os.path.join(drive, DEST_FOLDER_NAME)

        try:
            # Ensure destination exists if it's a subfolder
            if DEST_FOLDER_NAME and not os.path.exists(dest):
                os.makedirs(dest)

            # Normalize the source path to use backslashes for robocopy's reliability on Windows
            src_normalized = os.path.normpath(src)

            cmd = ["robocopy", src_normalized, dest, "/MIR", "/R:1", "/W:1", "/NP", "/NDL", "/NFL", f"/LOG+:{LOG_FILE_PATH}"]
            print(f"Executing command for drive {drive}: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode <= 8:
                self._update_status(drive, "Done", "100%")
                winsound.MessageBeep(winsound.MB_OK)
            else:
                self._update_status(drive, f"Error (code {result.returncode}, see log)", "0%")
                print(f"Error syncing to {drive}. Robocopy exit code: {result.returncode}")
        except Exception as e:
            self._update_status(drive, "Critical Error", "0%")
            print(f"A critical error occurred while syncing to {drive}: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = USBSyncApp(root)
    root.mainloop()
