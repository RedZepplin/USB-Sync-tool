# USB Sync Tool

A simple yet powerful Windows utility with a graphical user interface (GUI) for automatically or manually synchronizing a local folder to any connected USB drive. It's perfect for creating backups, distributing files, or preparing multiple USB drives with the same content.

## Features

- **User-Friendly Interface:** A clean and modern GUI built with Python's `tkinter`.
- **Automatic Drive Detection:** Uses `psutil` to automatically detect when USB drives are plugged in or removed.
- **Flexible Sync Modes:**
  - **Automatic Sync:** When enabled, automatically copies files to any newly connected USB drive.
  - **Manual Sync:** Allows you to select a specific drive from the list and sync it with a button click.
- **Robust Copying:** Leverages Windows' powerful `robocopy` command for reliable and efficient file mirroring.
- **Drive Renaming:** Optionally rename drives automatically after a successful sync.
- **Portable Setups:** Right-click to save the current configuration (source folder, rename settings) into a self-contained, distributable folder that's ready to run.
- **Detailed Logging:** All sync operations are appended to a single `usbsync.log` file for easy debugging.
- **Standalone Executable:** Can be easily compiled into a single `.exe` file for use on any Windows machine without needing Python installed.

## Usage (Running from Source)

To run the application directly from the Python source code, follow these steps.

### 1. Prerequisites

- Python 3.6+
- The `psutil` library

### 2. Installation

Clone this repository and install the required packages using the `requirements.txt` file:

```bash
git clone <repository_url>
cd <repository_folder>
pip install -r requirements.txt
```

### 3. Running the Application

Execute the main script from your terminal:

```bash
python USBSyncApp.py
```

## Compiling into an Executable (.exe)

This project uses `PyInstaller` to create a standalone Windows executable. This allows you to run the application on computers that do not have Python installed.

### 1. Prerequisites

Install `PyInstaller` using pip:

```bash
pip install pyinstaller
```

### 2. Build the Executable

The repository includes a `USBSyncApp.spec` file, which is pre-configured for building the application correctly (as a windowed app, not a console app).

Run the following command in the project's root directory:

```bash
pyinstaller USBSyncApp.spec
```

### 3. Locate the Application

The standalone `USBSyncApp.exe` will be created in the `dist` folder. You can copy this file to any other Windows computer and run it.
