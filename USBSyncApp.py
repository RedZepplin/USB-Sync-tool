import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import subprocess
import time
import os
import psutil
import winsound
import ctypes
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
        self.root.geometry("650x650")

        # --- Style ---
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")  # Use a cleaner, more modern theme
        self.sync_enabled = tk.BooleanVar(value=False)
        self.source_folder = tk.StringVar()
        self.rename_enabled = tk.BooleanVar(value=False)
        self.new_drive_label_var = tk.StringVar()
        self.drive_status = {}
        self.drive_threads = {}

        # Thread-safe communication
        self.ui_queue = queue.Queue()
        self.status_lock = threading.Lock()

        # Register the validation command for the rename entry
        self.vcmd = (self.root.register(self._validate_label), '%P')

        self.setup_ui()
        # Start the background polling thread
        self.sync_enabled.trace_add("write", self._on_sync_toggled)
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.process_queue()

    def setup_ui(self):
        # Main container frame with padding
        main_frame = ttk.Frame(self.root, padding="10 10 10 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Source Selection Frame ---
        source_frame = ttk.LabelFrame(main_frame, text="1. Select Source Folder", padding="10")
        source_frame.pack(fill=tk.X, pady=(0, 10))
        source_frame.columnconfigure(1, weight=1)  # Make the entry expand

        select_button = ttk.Button(source_frame, text="Select Folder...", command=self.select_source)
        select_button.grid(row=0, column=0, sticky="w")

        source_entry = ttk.Entry(source_frame, textvariable=self.source_folder, state="readonly")
        source_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        # --- Controls Frame ---
        controls_frame = ttk.LabelFrame(main_frame, text="2. Control Syncing", padding="10")
        controls_frame.pack(fill=tk.X, pady=(0, 10))

        sync_check = ttk.Checkbutton(controls_frame, text="Automatic Sync", variable=self.sync_enabled)
        sync_check.pack(side=tk.LEFT)
        log_button = ttk.Button(controls_frame, text="View Log File", command=self.view_log)
        log_button.pack(side=tk.RIGHT)

        # --- Post-Sync Actions Frame ---
        post_sync_frame = ttk.LabelFrame(main_frame, text="3. Post-Sync Actions", padding="10")
        post_sync_frame.pack(fill=tk.X, pady=(0, 10))
        post_sync_frame.columnconfigure(1, weight=1)

        self.rename_enabled.trace_add("write", self._on_rename_toggled)
        rename_check = ttk.Checkbutton(post_sync_frame, text="Rename drive after sync to:", variable=self.rename_enabled)
        rename_check.grid(row=0, column=0, sticky="w")

        self.rename_entry = ttk.Entry(post_sync_frame, textvariable=self.new_drive_label_var, validate="key", validatecommand=self.vcmd)
        self.rename_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.rename_entry.state(['disabled'])

        # --- Drive List Frame ---
        drives_frame = ttk.LabelFrame(main_frame, text="Detected USB Drives", padding="10")
        drives_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(drives_frame, columns=("Drive", "Status", "Progress"), show="headings", height=8)
        self.tree.heading("Drive", text="Drive")
        self.tree.heading("Status", text="Status")
        self.tree.heading("Progress", text="Progress")
        self.tree.column("Drive", width=100, anchor="w")
        self.tree.column("Status", width=200, anchor="w")
        self.tree.column("Progress", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(drives_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Manual Action Frame ---
        manual_actions_frame = ttk.Frame(main_frame, padding="10 0 0 0")
        manual_actions_frame.pack(fill=tk.X)

        self.manual_sync_button = ttk.Button(manual_actions_frame, text="Sync Selected Drive", command=self._on_manual_sync_click)
        self.manual_sync_button.pack()
        self.manual_sync_button.state(['!disabled'])

        # --- Status Bar ---
        self.status_var = tk.StringVar(value="Ready. Select a source folder to begin.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", padding="2 5 2 5")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def select_source(self):
        folder = filedialog.askdirectory()
        if folder:
            self.source_folder.set(folder)
            self.status_var.set(f"Source folder set to: {folder}")

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
            if not self.source_folder.get():
                messagebox.showwarning("Warning", "Please select a source folder before enabling sync.")
                self.sync_enabled.set(False)
                return
            self.status_var.set("Automatic sync enabled. Searching for ready drives...")
            self.manual_sync_button.state(['disabled'])
            self.ui_queue.put(("trigger_sync_all", None))
        else:
            self.status_var.set("Automatic sync disabled. Select a drive and click 'Sync Selected'.")
            self.manual_sync_button.state(['!disabled'])

    def _on_rename_toggled(self, *args):
        """Callback when the 'Rename drive' checkbox is changed."""
        if self.rename_enabled.get():
            self.rename_entry.state(['!disabled'])
        else:
            self.rename_entry.state(['disabled'])

    def _validate_label(self, new_value):
        """Validation function for the drive label entry."""
        if " " in new_value:
            return False
        if len(new_value) > 11:
            return False
        return True

    def view_log(self):
        """Opens the log file with the default application."""
        if not os.path.exists(LOG_FILE_PATH):
            messagebox.showinfo("Info", "Log file does not exist yet. It will be created on the first sync.")
            return
        try:
            os.startfile(LOG_FILE_PATH)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open log file:\n{e}")

    def _on_manual_sync_click(self):
        """Starts a sync for the currently selected drive in the list."""
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a drive from the list to sync.")
            return

        if not self.source_folder.get():
            messagebox.showwarning("No Source Folder", "Please select a source folder before syncing.")
            return

        drive_id = selected_items[0]
        self._start_sync_if_ready(drive_id)

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
        self.status_var.set(f"Syncing to {drive}...")
        dest = os.path.join(drive, DEST_FOLDER_NAME)

        try:
            # Ensure destination exists if it's a subfolder
            if DEST_FOLDER_NAME and not os.path.exists(dest):
                os.makedirs(dest)

            # Normalize the source path to use backslashes for robocopy's reliability on Windows
            src_normalized = os.path.normpath(src)

            # Add CREATE_NO_WINDOW to prevent console flash
            cmd = ["robocopy", src_normalized, dest, "/MIR", "/R:1", "/W:1", "/NP", "/NDL", "/NFL", f"/LOG+:{LOG_FILE_PATH}"]
            print(f"Executing command for drive {drive}: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW)

            if result.returncode <= 8:
                rename_successful = False
                rename_attempted = False
                # Check if renaming is enabled and a label is provided
                if self.rename_enabled.get():
                    new_label = self.new_drive_label_var.get().strip()
                    if new_label:
                        rename_attempted = True
                        self.status_var.set(f"Renaming {drive} to '{new_label}'...")
                        try:
                            drive_letter = drive.strip('\\')
                            # Input is pre-validated, so we can pass it directly.
                            rename_cmd = ["cmd", "/c", "label", drive_letter, new_label]
                            rename_result = subprocess.run(rename_cmd, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                            if rename_result.returncode == 0:
                                rename_successful = True
                            else:
                                print(f"Warning: Failed to rename {drive}. Stderr: {rename_result.stderr.strip()}")
                        except Exception as rename_e:
                            print(f"Error during rename of {drive}: {rename_e}")

                # Update final status
                if rename_successful:
                    self.status_var.set(f"Successfully synced and renamed {drive}.")
                elif rename_attempted: # A rename was attempted but failed
                    self.status_var.set(f"Sync to {drive} done, but rename failed.")
                else: # No rename was attempted
                    self.status_var.set(f"Successfully synced to {drive}.")
                self._update_status(drive, "Done", "100%")
                winsound.MessageBeep(winsound.MB_OK)
            else:
                self._update_status(drive, f"Error (code {result.returncode}, see log)", "0%")
                self.status_var.set(f"Error syncing to {drive}. Check log for details.")
                print(f"Error syncing to {drive}. Robocopy exit code: {result.returncode}")
        except Exception as e:
            self._update_status(drive, "Critical Error", "0%")
            self.status_var.set(f"A critical error occurred while syncing to {drive}.")
            print(f"A critical error occurred while syncing to {drive}: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = USBSyncApp(root)
    root.mainloop()
