#!/usr/bin/env python3
"""
PDF/DOCX File Manager - Portable Windows Application
A comprehensive file tracking and management system for PDF and DOCX files.

Developed by Sheikh Nomun Islam
"""

import sys
import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import subprocess
import platform

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QLineEdit,
    QComboBox, QTextEdit, QSplitter, QGroupBox, QFileDialog,
    QMessageBox, QDialog, QDialogButtonBox, QSpinBox, QProgressBar,
    QMenuBar, QMenu, QStatusBar, QTabWidget, QCheckBox, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSettings, QUrl
from PySide6.QtGui import QFont, QIcon, QPalette, QColor, QAction, QCursor, QDesktopServices

# File monitoring
WATCHDOG_AVAILABLE = False
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    Observer = None
    FileSystemEventHandler = None
    print("Info: File monitoring disabled (watchdog not available)")
except Exception as e:
    Observer = None
    FileSystemEventHandler = None
    print(f"Info: File monitoring disabled ({str(e)})")


class FileTracker:
    """Core file tracking and data management class."""
    
    def __init__(self, json_path: str = "library.json"):
        self.json_path = json_path
        self.data = {
            "version": "1.0",
            "folders": [],
            "files": [],
            "settings": {
                "theme": "dark",
                "auto_refresh": True,
                "backup_location": ""
            }
        }
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file."""
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    # Migrate old versions if needed
                    if loaded_data.get("version") != "1.0":
                        loaded_data = self._migrate_data(loaded_data)
                    self.data.update(loaded_data)
        except Exception as e:
            print(f"Error loading data: {e}")
    
    def save_data(self):
        """Save data to JSON file with error handling."""
        try:
            # Create backup directory if specified
            backup_dir = os.path.dirname(self.json_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            
            # Create a backup of existing file
            if os.path.exists(self.json_path):
                backup_path = self.json_path + '.backup'
                try:
                    import shutil
                    shutil.copy2(self.json_path, backup_path)
                except:
                    pass  # Backup failed, but continue
            
            # Write to temporary file first, then rename
            temp_path = self.json_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename (safer)
            if os.path.exists(self.json_path):
                os.replace(temp_path, self.json_path)
            else:
                os.rename(temp_path, self.json_path)
                
            return True
            
        except PermissionError:
            print(f"Permission denied saving to: {self.json_path}")
            return False
        except Exception as e:
            print(f"Error saving data: {e}")
            # Try to clean up temp file
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
            return False
    
    def _migrate_data(self, old_data):
        """Migrate data from older versions."""
        # Future migration logic here
        old_data["version"] = "1.0"
        return old_data
    
    def add_folder(self, folder_path: str):
        """Add a root folder to track."""
        if folder_path not in self.data["folders"]:
            self.data["folders"].append(folder_path)
            self.save_data()
    
    def remove_folder(self, folder_path: str):
        """Remove a root folder."""
        if folder_path in self.data["folders"]:
            self.data["folders"].remove(folder_path)
            # Remove files from this folder
            self.data["files"] = [f for f in self.data["files"] 
                                if not f["full_path"].startswith(folder_path)]
            self.save_data()
    
    def scan_folders(self) -> Dict[str, List[str]]:
        """Scan all root folders for PDF and DOCX files."""
        found_files = {}
        extensions = {'.pdf', '.docx'}
        
        for folder in self.data["folders"]:
            if not os.path.exists(folder):
                continue
                
            folder_files = []
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if Path(file).suffix.lower() in extensions:
                        full_path = os.path.join(root, file)
                        folder_files.append(full_path)
            
            found_files[folder] = folder_files
        
        return found_files
    
    def update_file_list(self):
        """Update the file list based on current folder scan."""
        found_files = self.scan_folders()
        current_files = {f["full_path"]: f for f in self.data["files"]}
        new_files = []
        
        # Process found files
        for folder, files in found_files.items():
            for file_path in files:
                relative_path = os.path.relpath(file_path, folder)
                file_id = f"{Path(folder).name}/{relative_path}"
                
                if file_path in current_files:
                    # File exists, keep current data
                    new_files.append(current_files[file_path])
                else:
                    # Check for potential moved files
                    moved_file = self._check_for_moved_file(file_path, current_files)
                    if moved_file:
                        moved_file["full_path"] = file_path
                        moved_file["id"] = file_id
                        new_files.append(moved_file)
                    else:
                        # New file
                        new_files.append({
                            "id": file_id,
                            "full_path": file_path,
                            "status": "unread",
                            "last_page": None,
                            "last_opened": None,
                            "notes": ""
                        })
        
        self.data["files"] = new_files
        self.save_data()
    
    def _check_for_moved_file(self, new_path: str, current_files: Dict) -> Optional[Dict]:
        """Check if a file might have been moved based on filename and size."""
        new_name = os.path.basename(new_path)
        try:
            new_size = os.path.getsize(new_path)
            new_mtime = os.path.getmtime(new_path)
        except:
            return None
        
        for old_path, file_data in current_files.items():
            if not os.path.exists(old_path):
                old_name = os.path.basename(old_path)
                if old_name == new_name:
                    try:
                        # Additional checks could be added here (file hash, etc.)
                        return file_data
                    except:
                        continue
        return None
    
    def update_file_status(self, file_path: str, status: str, last_page: Optional[int] = None):
        """Update file status and progress with error handling."""
        try:
            for file_data in self.data["files"]:
                if file_data["full_path"] == file_path:
                    file_data["status"] = status
                    if last_page is not None:
                        file_data["last_page"] = last_page
                    file_data["last_opened"] = datetime.now().isoformat()
                    break
            
            # Save data and return success status
            return self.save_data()
            
        except Exception as e:
            print(f"Error updating file status: {e}")
            return False
    
    def update_file_notes(self, file_path: str, notes: str):
        """Update file notes with error handling."""
        try:
            for file_data in self.data["files"]:
                if file_data["full_path"] == file_path:
                    file_data["notes"] = notes
                    break
            
            return self.save_data()
            
        except Exception as e:
            print(f"Error updating file notes: {e}")
            return False
    
    def get_files_by_filter(self, status_filter: str = "all") -> List[Dict]:
        """Get files filtered by status."""
        if status_filter == "all":
            return self.data["files"]
        return [f for f in self.data["files"] if f["status"] == status_filter]


class FileSystemWatcher(QThread):
    """File system monitoring thread."""
    
    files_changed = Signal()
    
    def __init__(self, folders: List[str]):
        super().__init__()
        self.folders = folders
        self.observer = None
        self.should_stop = False
    
    def run(self):
        if not WATCHDOG_AVAILABLE or not self.folders or not Observer:
            return
        
        try:            
            class Handler(FileSystemEventHandler):
                def __init__(self, watcher):
                    super().__init__()
                    self.watcher = watcher
                
                def on_any_event(self, event):
                    if event.is_directory:
                        return
                    if event.src_path.lower().endswith(('.pdf', '.docx')):
                        self.watcher.files_changed.emit()
            
            self.observer = Observer()
            handler = Handler(self)
            
            for folder in self.folders:
                if os.path.exists(folder):
                    self.observer.schedule(handler, folder, recursive=True)
            
            self.observer.start()
            
            while not self.should_stop:
                self.msleep(1000)
            
            if self.observer:
                self.observer.stop()
                self.observer.join()
                
        except Exception as e:
            print(f"File watching error: {e}")
            return
    
    def stop_watching(self):
        self.should_stop = True


class PageProgressDialog(QDialog):
    """Dialog for updating page progress."""
    
    def __init__(self, parent=None, current_page=None):
        super().__init__(parent)
        self.setWindowTitle("Update Progress")
        self.setModal(True)
        self.resize(300, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("What page did you reach?"))
        
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setRange(0, 9999)
        if current_page:
            self.page_spinbox.setValue(current_page)
        layout.addWidget(self.page_spinbox)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_page(self):
        return self.page_spinbox.value()

class AboutDialog(QDialog):
    """About dialog showing developer information."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PDF/DOCX File Manager")
        self.setModal(True)
        self.setFixedSize(800, 400)  # Much wider but more compact height
        self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)  # Prevent resize issues
        
        # Main horizontal layout for wider design
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(25)
        
        # Left side - Main info
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(12)
        
        # Compact title
        title = QLabel("PDF/DOCX File Manager")
        title.setStyleSheet("""
            QLabel {
                font-size: 20px; 
                font-weight: bold; 
                color: #2a5d2a;
                background: transparent;
                margin: 5px 0px;
            }
        """)
        title.setAlignment(Qt.AlignLeft)
        left_layout.addWidget(title)
        
        # Compact version
        version = QLabel("Version 1.0")
        version.setStyleSheet("""
            QLabel {
                font-size: 12px; 
                color: #cccccc;
                background: transparent;
                margin: 0px 0px 10px 0px;
            }
        """)
        version.setAlignment(Qt.AlignLeft)
        left_layout.addWidget(version)
        
        # Developer info - compact
        dev_info = QLabel()
        dev_info.setText("""
<div style="line-height: 1.4;">
    <p style="color: #ffffff; margin: 0px 0px 8px 0px; font-size: 14px; font-weight: bold;">
        Developed by Sheikh Nomun Islam
    </p>
    <p style="font-style: italic; color: #e0e0e0; margin: 0px 0px 12px 0px; font-size: 11px; line-height: 1.3;">
        "I was tired of forgetting which PDF or DOCX file I was reading, what page I left off, or where the file even was—so I built this."
    </p>
    <p style="color: #ffffff; margin: 0px 0px 8px 0px; font-size: 10px; line-height: 1.3;">
        A comprehensive, portable file management tool to track and organize your documents with intelligent progress monitoring, status updates, and folder-aware structure.
    </p>
    <p style="color: #b0b0b0; font-size: 9px; margin: 0px; line-height: 1.2;">
        Built with Python and PySide6 for modern, efficient, and cross-platform file organization.
    </p>
</div>
        """)
        dev_info.setWordWrap(True)
        dev_info.setStyleSheet("background: transparent; padding: 10px; border-radius: 5px; background-color: #2d2d2d; border: 1px solid #3a3a3a;")
        left_layout.addWidget(dev_info)
        
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        main_layout.addWidget(left_panel, 2)  # Takes 2/3 of space
        
        # Right side - Contact info (compact)
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(10)
        
        # Compact contact section
        contact_frame = QFrame()
        contact_frame.setStyleSheet("""
            QFrame {
                background-color: #3a3a3a;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        contact_layout = QVBoxLayout()
        contact_layout.setContentsMargins(8, 8, 8, 8)
        contact_layout.setSpacing(8)
        
        # Compact title
        contact_title = QLabel("Get in Touch")
        contact_title.setStyleSheet("""
            QLabel {
                font-weight: bold; 
                font-size: 12px; 
                color: #ffffff; 
                background: transparent;
                margin: 0px 0px 5px 0px;
                text-align: center;
            }
        """)
        contact_title.setAlignment(Qt.AlignCenter)
        contact_layout.addWidget(contact_title)
        
        # Facebook link - compact
        facebook_link = QLabel('<a href="https://www.facebook.com/sheikh.nomun" style="color: #4267B2; text-decoration: none; font-weight: bold; font-size: 10px;">🤙 Connect on Facebook</a>')
        facebook_link.setAlignment(Qt.AlignCenter)
        facebook_link.setOpenExternalLinks(True)
        facebook_link.setStyleSheet("background: transparent; margin: 3px 0px; padding: 3px;")
        contact_layout.addWidget(facebook_link)
        
        # Email - compact
        email_label = QLabel("📧 nomun.s@outlook.com")
        email_label.setAlignment(Qt.AlignCenter)
        email_label.setStyleSheet("""
            QLabel {
                font-size: 10px; 
                color: #e0e0e0;
                background: transparent;
                margin: 3px 0px;
            }
        """)
        contact_layout.addWidget(email_label)
        
        # Feedback note - compact
        feedback_note = QLabel("Feel free to report bugs, suggest features, or share feedback!")
        feedback_note.setAlignment(Qt.AlignCenter)
        feedback_note.setWordWrap(True)
        feedback_note.setStyleSheet("""
            QLabel {
                font-size: 8px; 
                color: #999999; 
                font-style: italic;
                background: transparent;
                margin: 5px 0px;
                line-height: 1.2;
            }
        """)
        contact_layout.addWidget(feedback_note)
        
        contact_frame.setLayout(contact_layout)
        right_layout.addWidget(contact_frame)
        
        # Close button - compact
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setFixedSize(80, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5d2a;
                border: 1px solid #1e4d1e;
                color: #ffffff;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                margin: 8px 0px;
            }
            QPushButton:hover {
                background-color: #3a7d3a;
            }
            QPushButton:pressed {
                background-color: #1a4d1a;
            }
        """)
        right_layout.addWidget(close_btn, 0, Qt.AlignCenter)
        right_layout.addStretch()
        
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel, 1)  # Takes 1/3 of space
        
        self.setLayout(main_layout)

class SettingsDialog(QDialog):
    """Settings configuration dialog."""
    
    def __init__(self, parent=None, file_tracker=None):
        super().__init__(parent)
        self.file_tracker = file_tracker
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(500, 400)
        
        layout = QVBoxLayout()
        
        # JSON backup location
        backup_group = QGroupBox("Backup Location")
        backup_layout = QVBoxLayout()
        
        self.backup_path = QLineEdit()
        self.backup_path.setText(file_tracker.json_path)
        backup_layout.addWidget(self.backup_path)
        
        backup_browse = QPushButton("Browse...")
        backup_browse.clicked.connect(self.browse_backup_location)
        backup_layout.addWidget(backup_browse)
        
        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)
        
        # Root folders management
        folders_group = QGroupBox("Root Folders")
        folders_layout = QVBoxLayout()
        
        self.folders_list = QTreeWidget()
        self.folders_list.setHeaderLabels(["Folder Path"])
        self.update_folders_list()
        folders_layout.addWidget(self.folders_list)
        
        folder_buttons = QHBoxLayout()
        add_folder_btn = QPushButton("Add Folder")
        add_folder_btn.clicked.connect(self.add_folder)
        remove_folder_btn = QPushButton("Remove Folder")
        remove_folder_btn.clicked.connect(self.remove_folder)
        
        folder_buttons.addWidget(add_folder_btn)
        folder_buttons.addWidget(remove_folder_btn)
        folders_layout.addLayout(folder_buttons)
        
        folders_group.setLayout(folders_layout)
        layout.addWidget(folders_group)
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def browse_backup_location(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Select JSON Backup Location", self.backup_path.text(),
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.backup_path.setText(file_path)
    
    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Track")
        if folder:
            self.file_tracker.add_folder(folder)
            self.update_folders_list()
    
    def remove_folder(self):
        current = self.folders_list.currentItem()
        if current:
            folder = current.text(0)
            reply = QMessageBox.question(
                self, "Remove Folder",
                f"Remove folder from tracking?\n{folder}\n\nThis will also remove all file progress data for this folder.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.file_tracker.remove_folder(folder)
                self.update_folders_list()
    
    def update_folders_list(self):
        self.folders_list.clear()
        for folder in self.file_tracker.data["folders"]:
            item = QTreeWidgetItem([folder])
            self.folders_list.addTopLevelItem(item)
    
    def accept(self):
        """Save settings with error handling."""
        try:
            # Save backup location
            new_path = self.backup_path.text().strip()
            if new_path and new_path != self.file_tracker.json_path:
                # Validate the path
                backup_dir = os.path.dirname(new_path)
                if backup_dir and not os.path.exists(backup_dir):
                    reply = QMessageBox.question(
                        self, "Create Directory",
                        f"Directory doesn't exist:\n{backup_dir}\n\nCreate it?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        try:
                            os.makedirs(backup_dir, exist_ok=True)
                        except Exception as e:
                            QMessageBox.warning(self, "Error", f"Could not create directory:\n{str(e)}")
                            return
                    else:
                        return
                
                # Test write permissions
                try:
                    test_data = {"test": True}
                    with open(new_path, 'w') as f:
                        json.dump(test_data, f)
                    os.remove(new_path)  # Clean up test file
                except Exception as e:
                    QMessageBox.warning(self, "Permission Error", 
                                       f"Cannot write to location:\n{new_path}\n\nError: {str(e)}")
                    return
                
                # Move existing data if it exists
                if os.path.exists(self.file_tracker.json_path) and new_path != self.file_tracker.json_path:
                    try:
                        import shutil
                        shutil.copy2(self.file_tracker.json_path, new_path)
                    except Exception as e:
                        reply = QMessageBox.question(
                            self, "Copy Failed",
                            f"Could not copy existing data:\n{str(e)}\n\nContinue anyway?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            return
                
                self.file_tracker.json_path = new_path
                success = self.file_tracker.save_data()
                if not success:
                    QMessageBox.warning(self, "Save Error", "Could not save to new location")
                    return
            
            super().accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"An error occurred:\n{str(e)}")


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.file_tracker = FileTracker()
        self.file_watcher = None
        self.current_file_data = None
        
        self.setWindowTitle("PDF/DOCX File Manager")
        self.setGeometry(100, 100, 1200, 800)
        
        self.setup_ui()
        self.apply_dark_theme()
        self.refresh_file_list()
        self.setup_file_watcher()
    
    def setup_ui(self):
        """Setup the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Content area with splitter
        content_splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - File tree
        left_panel = self.create_left_panel()
        content_splitter.addWidget(left_panel)
        
        # Right panel - File details
        right_panel = self.create_right_panel()
        content_splitter.addWidget(right_panel)
        
        content_splitter.setSizes([400, 300])
        main_layout.addWidget(content_splitter)
        
        # Bottom signature section
        signature_widget = self.create_signature_widget()
        main_layout.addWidget(signature_widget)
        
        central_widget.setLayout(main_layout)
        
        # Menu bar
        self.create_menu_bar()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_signature_widget(self):
        """Create the signature widget with clickable name."""
        signature_frame = QFrame()
        signature_frame.setFixedHeight(35)
        signature_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-top: 1px solid #3a3a3a;
                margin: 0px;
                padding: 0px;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 15, 5)
        
        # Add stretch to push content to the right
        layout.addStretch()
        
        # Passion project text
        passion_label = QLabel("A passion project by ")
        passion_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 11px;
                font-style: italic;
                background: transparent;
                margin: 0px;
                padding: 0px;
            }
        """)
        layout.addWidget(passion_label)
        
        # Clickable name
        name_label = QLabel("Nomun")
        name_label.setStyleSheet("""
            QLabel {
                color: #2a5d2a;
                font-size: 11px;
                font-weight: bold;
                font-style: italic;
                background: transparent;
                margin: 0px;
                padding: 2px 4px;
                border-radius: 3px;
            }
            QLabel:hover {
                color: #3a7d3a;
                background-color: rgba(42, 93, 42, 0.1);
                text-decoration: underline;
            }
        """)
        name_label.setCursor(QCursor(Qt.PointingHandCursor))
        name_label.mousePressEvent = self.open_facebook_profile
        layout.addWidget(name_label)
        
        # Rocket emoji
        rocket_label = QLabel(" 🚀")
        rocket_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 12px;
                background: transparent;
                margin: 0px;
                padding: 0px;
            }
        """)
        layout.addWidget(rocket_label)
        
        signature_frame.setLayout(layout)
        return signature_frame
    
    def open_facebook_profile(self, event):
        """Open my Facebook profile in default browser."""
        try:
            QDesktopServices.openUrl(QUrl("https://www.facebook.com/sheikh.nomun"))
        except Exception as e:
            print(f"Error opening Facebook profile: {e}")
            QMessageBox.information(self, "Facebook Profile", 
                                   "Visit: https://www.facebook.com/sheikh.nomun")
    
    def create_left_panel(self):
        """Create the left panel with file tree and filters."""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Filter controls
        filter_group = QGroupBox("Filters")
        filter_layout = QVBoxLayout()
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Unread", "In-Progress", "Read"])
        self.status_filter.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(QLabel("Status:"))
        filter_layout.addWidget(self.status_filter)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "Status", "Last Opened"])
        self.sort_combo.currentTextChanged.connect(self.apply_sort)
        filter_layout.addWidget(QLabel("Sort by:"))
        filter_layout.addWidget(self.sort_combo)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # File tree
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["File", "Status", "Page"])
        self.file_tree.itemSelectionChanged.connect(self.on_file_selected)
        self.file_tree.itemDoubleClicked.connect(self.open_file)
        layout.addWidget(self.file_tree)
        
        # Control buttons
        button_layout = QVBoxLayout()
        
        self.refresh_btn = QPushButton("Refresh Library")
        self.refresh_btn.clicked.connect(self.refresh_file_list)
        button_layout.addWidget(self.refresh_btn)
        
        self.open_file_btn = QPushButton("Open File")
        self.open_file_btn.clicked.connect(self.open_file)
        self.open_file_btn.setEnabled(False)
        button_layout.addWidget(self.open_file_btn)
        
        layout.addLayout(button_layout)
        panel.setLayout(layout)
        
        return panel
    
    def create_right_panel(self):
        """Create the right panel with file details."""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # File details
        details_group = QGroupBox("File Details")
        details_layout = QVBoxLayout()
        
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setWordWrap(True)
        details_layout.addWidget(self.file_path_label)
        
        # Status controls
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        
        self.status_combo = QComboBox()
        self.status_combo.addItems(["unread", "in-progress", "read"])
        self.status_combo.currentTextChanged.connect(self.update_file_status_from_combo)
        status_layout.addWidget(self.status_combo)
        
        details_layout.addLayout(status_layout)
        
        # Page progress
        page_layout = QHBoxLayout()
        page_layout.addWidget(QLabel("Last Page:"))
        
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setRange(0, 9999)
        self.page_spinbox.valueChanged.connect(self.update_page_progress)
        page_layout.addWidget(self.page_spinbox)
        
        details_layout.addLayout(page_layout)
        
        # Last opened
        self.last_opened_label = QLabel("Last opened: Never")
        details_layout.addWidget(self.last_opened_label)
        
        # Notes
        details_layout.addWidget(QLabel("Notes:"))
        self.notes_text = QTextEdit()
        self.notes_text.setMaximumHeight(100)
        self.notes_text.textChanged.connect(self.on_notes_changed)
        details_layout.addWidget(self.notes_text)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Action buttons
        action_layout = QVBoxLayout()
        
        self.mark_read_btn = QPushButton("Mark as Read")
        self.mark_read_btn.clicked.connect(lambda: self.quick_status_change("read"))
        self.mark_read_btn.setEnabled(False)
        action_layout.addWidget(self.mark_read_btn)
        
        self.mark_progress_btn = QPushButton("Mark In-Progress")
        self.mark_progress_btn.clicked.connect(lambda: self.quick_status_change("in-progress"))
        self.mark_progress_btn.setEnabled(False)
        action_layout.addWidget(self.mark_progress_btn)
        
        layout.addLayout(action_layout)
        layout.addStretch()
        
        panel.setLayout(layout)
        return panel
    
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        refresh_action = QAction("Refresh Library", self)
        refresh_action.triggered.connect(self.refresh_file_list)
        view_menu.addAction(refresh_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def show_about(self):
        """Show about dialog."""
        dialog = AboutDialog(self)
        dialog.exec()
    
    def setup_file_watcher(self):
        """Setup file system monitoring."""
        if WATCHDOG_AVAILABLE and self.file_tracker.data["folders"]:
            self.file_watcher = FileSystemWatcher(self.file_tracker.data["folders"])
            self.file_watcher.files_changed.connect(self.on_files_changed)
            self.file_watcher.start()
    
    def apply_dark_theme(self):
        """Apply dark theme to the application."""
        # Set comprehensive stylesheet for professional dark theme
        self.setStyleSheet("""
            /* Main Window */
            QMainWindow {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            
            /* Panels and Groups */
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            
            QGroupBox {
                color: #ffffff;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                font-weight: bold;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                background-color: #1e1e1e;
            }
            
            /* Tree Widget */
            QTreeWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                selection-background-color: #2a5d2a;
                outline: none;
                font-size: 11px;
                show-decoration-selected: 1;
            }
            
            QTreeWidget::item {
                padding: 4px;
                border-bottom: 1px solid #3a3a3a;
                color: #ffffff;
                height: 20px;
            }
            
            QTreeWidget::item:selected {
                background-color: #2a5d2a;
                color: #ffffff;
            }
            
            QTreeWidget::item:hover {
                background-color: #3a3a3a;
                color: #ffffff;
            }
            
            QTreeWidget::branch {
                background: transparent;
            }
            
            QTreeWidget::branch:has-siblings:!adjoins-item {
                border-image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==) 0;
            }
            
            QTreeWidget::branch:has-siblings:adjoins-item {
                border-image: none;
                border-left: 1px solid #555;
            }
            
            QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
                border-image: none;
                border-left: 1px solid #555;
            }
            
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMCAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTMgMkw3IDVMMy44IiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iMSIgZmlsbD0ibm9uZSIvPgo8L3N2Zz4K);
            }
            
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                border-image: none;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMCAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTIgM0w1IDdMOCAzIiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iMSIgZmlsbD0ibm9uZSIvPgo8L3N2Zz4K);
            }
            
            /* Header for Tree Widget */
            QHeaderView::section {
                background-color: #3a3a3a;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #2d2d2d;
                font-weight: bold;
                font-size: 11px;
            }
            
            /* Buttons */
            QPushButton {
                background-color: #2a5d2a;
                border: 2px solid #1e4d1e;
                color: #ffffff;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-height: 20px;
            }
            
            QPushButton:hover {
                background-color: #3a7d3a;
                border-color: #2e5d2e;
            }
            
            QPushButton:pressed {
                background-color: #1a4d1a;
                border-color: #0e3d0e;
            }
            
            QPushButton:disabled {
                background-color: #404040;
                border-color: #2a2a2a;
                color: #808080;
            }
            
            /* ComboBox */
            QComboBox {
                background-color: #3a3a3a;
                border: 2px solid #4a4a4a;
                color: #ffffff;
                padding: 6px 10px;
                border-radius: 5px;
                font-size: 11px;
                min-height: 16px;
            }
            
            QComboBox:hover {
                border-color: #2a5d2a;
                background-color: #404040;
            }
            
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
                margin-right: 5px;
            }
            
            QComboBox QAbstractItemView {
                background-color: #3a3a3a;
                border: 1px solid #4a4a4a;
                color: #ffffff;
                selection-background-color: #2a5d2a;
            }
            
            /* LineEdit and SpinBox */
            QLineEdit, QSpinBox {
                background-color: #3a3a3a;
                border: 2px solid #4a4a4a;
                color: #ffffff;
                padding: 6px;
                border-radius: 5px;
                font-size: 11px;
                min-height: 16px;
            }
            
            QLineEdit:focus, QSpinBox:focus {
                border-color: #2a5d2a;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #4a4a4a;
                border: 1px solid #5a5a5a;
                width: 16px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #2a5d2a;
            }
            
            QSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 4px solid #ffffff;
            }
            
            QSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #ffffff;
            }
            
            /* TextEdit */
            QTextEdit {
                background-color: #3a3a3a;
                border: 2px solid #4a4a4a;
                color: #ffffff;
                padding: 6px;
                border-radius: 5px;
                font-size: 11px;
            }
            
            QTextEdit:focus {
                border-color: #2a5d2a;
            }
            
            /* Labels */
            QLabel {
                color: #ffffff;
                font-size: 11px;
            }
            
            /* Menu Bar */
            QMenuBar {
                background-color: #2d2d2d;
                color: #ffffff;
                border-bottom: 1px solid #3a3a3a;
                padding: 2px;
            }
            
            QMenuBar::item {
                background-color: transparent;
                padding: 6px 12px;
                margin: 0px;
            }
            
            QMenuBar::item:selected {
                background-color: #2a5d2a;
                border-radius: 4px;
            }
            
            QMenu {
                background-color: #2d2d2d;
                border: 1px solid #3a3a3a;
                color: #ffffff;
                padding: 4px;
            }
            
            QMenu::item {
                padding: 6px 20px;
                margin: 1px;
            }
            
            QMenu::item:selected {
                background-color: #2a5d2a;
                border-radius: 4px;
            }
            
            /* Status Bar */
            QStatusBar {
                background-color: #2d2d2d;
                color: #ffffff;
                border-top: 1px solid #3a3a3a;
                font-size: 11px;
                padding: 2px;
                min-height: 20px;
            }
            
            /* Signature Frame Specific Styles */
            QFrame#signatureFrame {
                background-color: #1a1a1a;
                border-top: 1px solid #3a3a3a;
            }
            
            /* Splitter */
            QSplitter::handle {
                background-color: #3a3a3a;
                width: 2px;
                height: 2px;
            }
            
            QSplitter::handle:hover {
                background-color: #2a5d2a;
            }
            
            /* Scrollbars */
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:vertical {
                background-color: #4a4a4a;
                border-radius: 6px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: #2a5d2a;
            }
            
            QScrollBar:horizontal {
                background-color: #2d2d2d;
                height: 12px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:horizontal {
                background-color: #4a4a4a;
                border-radius: 6px;
                min-width: 20px;
            }
            
            QScrollBar::handle:horizontal:hover {
                background-color: #2a5d2a;
            }
            
            QScrollBar::add-line, QScrollBar::sub-line {
                border: none;
                background: none;
            }
        """)
    
    def refresh_file_list(self):
        """Refresh the file list from folders with safety checks."""
        try:
            # Prevent rapid refreshes
            if hasattr(self, '_last_refresh'):
                import time
                if time.time() - self._last_refresh < 2:  # 2 second minimum between refreshes
                    self.status_bar.showMessage("Please wait before refreshing again...")
                    return
            
            self.status_bar.showMessage("Scanning folders...")
            QApplication.processEvents()
            
            # Disable refresh button temporarily
            self.refresh_btn.setEnabled(False)
            
            try:
                self.file_tracker.update_file_list()
                self.populate_tree()
                
                file_count = len(self.file_tracker.data["files"])
                self.status_bar.showMessage(f"✓ Found {file_count} files")
                
                import time
                self._last_refresh = time.time()
                
            finally:
                # Re-enable refresh button
                QTimer.singleShot(1000, lambda: self.refresh_btn.setEnabled(True))
                
        except Exception as e:
            print(f"Error refreshing file list: {e}")
            self.status_bar.showMessage("✗ Error scanning folders")
            self.refresh_btn.setEnabled(True)
    
    def populate_tree(self):
        """Populate the file tree widget with improved folder/file indicators."""
        self.file_tree.clear()
        
        # Get filtered files
        filter_text = self.status_filter.currentText().lower()
        if filter_text == "all":
            files = self.file_tracker.data["files"]
        else:
            filter_map = {"in-progress": "in-progress"}
            filter_key = filter_map.get(filter_text, filter_text)
            files = [f for f in self.file_tracker.data["files"] if f["status"] == filter_key]
        
        # Sort files
        sort_key = self.sort_combo.currentText()
        if sort_key == "Name":
            files.sort(key=lambda x: os.path.basename(x["full_path"]).lower())
        elif sort_key == "Status":
            files.sort(key=lambda x: x["status"])
        elif sort_key == "Last Opened":
            files.sort(key=lambda x: x["last_opened"] or "", reverse=True)
        
        # Group by root folder
        folder_items = {}
        
        for file_data in files:
            full_path = file_data["full_path"]
            
            # Find root folder
            root_folder = None
            for folder in self.file_tracker.data["folders"]:
                if full_path.startswith(folder):
                    root_folder = folder
                    break
            
            if not root_folder:
                continue
            
            # Create folder item if needed
            if root_folder not in folder_items:
                folder_name = f"📁 {os.path.basename(root_folder) or root_folder}"
                folder_item = QTreeWidgetItem([folder_name, "", ""])
                folder_item.setData(0, Qt.UserRole, {"type": "folder", "path": root_folder})
                self.file_tree.addTopLevelItem(folder_item)
                folder_items[root_folder] = folder_item
            
            # Add file item
            rel_path = os.path.relpath(full_path, root_folder)
            file_name = os.path.basename(full_path)
            
            # Add file type icon
            if file_name.lower().endswith('.pdf'):
                file_name = f"📄 {file_name}"
            elif file_name.lower().endswith('.docx'):
                file_name = f"📝 {file_name}"
            
            status = file_data["status"].replace("-", " ").title()
            page = str(file_data["last_page"]) if file_data["last_page"] else "0"
            
            file_item = QTreeWidgetItem([file_name, status, page])
            file_item.setData(0, Qt.UserRole, {"type": "file", "data": file_data})
            
            # Create subfolder structure if needed
            path_parts = Path(rel_path).parts[:-1]  # Exclude filename
            current_parent = folder_items[root_folder]
            
            for part in path_parts:
                # Check if subfolder already exists
                subfolder_item = None
                for i in range(current_parent.childCount()):
                    child = current_parent.child(i)
                    child_data = child.data(0, Qt.UserRole)
                    if (child_data and child_data.get("type") == "subfolder" and 
                        child.text(0) == f"📁 {part}"):
                        subfolder_item = child
                        break
                
                if not subfolder_item:
                    subfolder_item = QTreeWidgetItem([f"📁 {part}", "", ""])
                    subfolder_item.setData(0, Qt.UserRole, {"type": "subfolder"})
                    current_parent.addChild(subfolder_item)
                
                current_parent = subfolder_item
            
            current_parent.addChild(file_item)
        
        # Expand all items
        self.file_tree.expandAll()
        
        # Resize columns
        self.file_tree.resizeColumnToContents(0)
        self.file_tree.resizeColumnToContents(1)
        self.file_tree.resizeColumnToContents(2)
    
    def apply_filter(self):
        """Apply status filter."""
        self.populate_tree()
    
    def apply_sort(self):
        """Apply sorting."""
        self.populate_tree()
    
    def on_file_selected(self):
        """Handle file selection."""
        current = self.file_tree.currentItem()
        if not current:
            self.clear_file_details()
            return
        
        item_data = current.data(0, Qt.UserRole)
        if not item_data or item_data.get("type") != "file":
            self.clear_file_details()
            return
        
        file_data = item_data["data"]
        self.show_file_details(file_data)
    
    def show_file_details(self, file_data):
        """Show details for selected file."""
        try:
            self.current_file_data = file_data
            
            self.file_path_label.setText(file_data["full_path"])
            
            # Block signals to prevent recursive calls
            self.status_combo.blockSignals(True)
            self.page_spinbox.blockSignals(True)
            self.notes_text.blockSignals(True)
            
            self.status_combo.setCurrentText(file_data["status"])
            self.page_spinbox.setValue(file_data["last_page"] or 0)
            
            if file_data["last_opened"]:
                try:
                    dt = datetime.fromisoformat(file_data["last_opened"])
                    self.last_opened_label.setText(f"Last opened: {dt.strftime('%Y-%m-%d %H:%M')}")
                except:
                    self.last_opened_label.setText("Last opened: Unknown")
            else:
                self.last_opened_label.setText("Last opened: Never")
            
            self.notes_text.setPlainText(file_data.get("notes", ""))
            
            # Re-enable signals
            self.status_combo.blockSignals(False)
            self.page_spinbox.blockSignals(False)
            self.notes_text.blockSignals(False)
            
            # Enable buttons
            self.open_file_btn.setEnabled(True)
            self.mark_read_btn.setEnabled(True)
            self.mark_progress_btn.setEnabled(True)
            
        except Exception as e:
            print(f"Error showing file details: {e}")
            self.clear_file_details()
    
    def clear_file_details(self):
        """Clear file details panel."""
        self.current_file_data = None
        self.file_path_label.setText("No file selected")
        self.last_opened_label.setText("Last opened: Never")
        
        # Block signals to prevent unnecessary calls
        self.notes_text.blockSignals(True)
        self.notes_text.clear()
        self.notes_text.blockSignals(False)
        
        # Disable buttons
        self.open_file_btn.setEnabled(False)
        self.mark_read_btn.setEnabled(False)
        self.mark_progress_btn.setEnabled(False)
    
    def open_file(self):
        """Open the selected file in default application."""
        if not self.current_file_data:
            return
        
        file_path = self.current_file_data["full_path"]
        
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "File Not Found", 
                               f"File not found:\n{file_path}")
            return
        
        try:
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', file_path])
            else:  # Linux
                subprocess.run(['xdg-open', file_path])
            
            # Show progress dialog after a delay
            QTimer.singleShot(2000, self.show_progress_dialog)
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{str(e)}")
    
    def show_progress_dialog(self):
        """Show dialog to update reading progress with better error handling."""
        if not self.current_file_data:
            return
        
        try:
            current_page = self.current_file_data.get("last_page", 0)
            dialog = PageProgressDialog(self, current_page)
            
            if dialog.exec() == QDialog.Accepted:
                new_page = dialog.get_page()
                if new_page > 0:
                    self.update_file_progress(new_page, "in-progress")
                else:
                    self.update_file_progress(None, "unread")
        except Exception as e:
            print(f"Error in progress dialog: {e}")
            self.status_bar.showMessage("✗ Error updating progress")
    
    def on_notes_changed(self):
        """Handle notes text changes with auto-save."""
        if not self.current_file_data:
            return
        
        try:
            notes = self.notes_text.toPlainText()
            file_path = self.current_file_data["full_path"]
            
            # Update notes with error handling
            success = self.file_tracker.update_file_notes(file_path, notes)
            
            if success:
                self.current_file_data["notes"] = notes
                self.status_bar.showMessage("✓ Notes saved")
            else:
                self.status_bar.showMessage("✗ Failed to save notes")
                
        except Exception as e:
            print(f"Error updating notes: {e}")
            self.status_bar.showMessage("✗ Error saving notes")
    
    def update_file_progress(self, page, status):
        """Update file progress and status with error handling."""
        if not self.current_file_data:
            return
        
        try:
            file_path = self.current_file_data["full_path"]
            
            # Update in file tracker with error handling
            success = self.file_tracker.update_file_status(file_path, status, page)
            
            if success:
                # Update local data
                self.current_file_data["last_page"] = page
                self.current_file_data["status"] = status
                self.current_file_data["last_opened"] = datetime.now().isoformat()
                
                # Refresh display
                self.show_file_details(self.current_file_data)
                self.populate_tree()
                
                self.status_bar.showMessage(f"✓ Updated: Page {page or 0}, Status: {status}")
            else:
                # Show error message
                self.status_bar.showMessage("✗ Failed to save progress - check file permissions")
                QMessageBox.warning(self, "Save Error", 
                                   f"Could not save progress to library.json\n"
                                   f"Please check file permissions and try again.")
        except Exception as e:
            print(f"Error updating file progress: {e}")
            self.status_bar.showMessage("✗ Error updating progress")
    
    def update_file_status_from_combo(self):
        """Update file status from combo box with error handling."""
        if not self.current_file_data:
            return
        
        try:
            new_status = self.status_combo.currentText()
            current_page = self.current_file_data.get("last_page")
            
            self.update_file_progress(current_page, new_status)
        except Exception as e:
            print(f"Error updating status: {e}")
            self.status_bar.showMessage("✗ Error updating status")
    
    def update_page_progress(self):
        """Update page progress from spinbox with error handling."""
        if not self.current_file_data:
            return
        
        try:
            new_page = self.page_spinbox.value()
            current_status = self.current_file_data["status"]
            
            # Auto-update status based on page
            if new_page > 0 and current_status == "unread":
                current_status = "in-progress"
            
            self.update_file_progress(new_page if new_page > 0 else None, current_status)
        except Exception as e:
            print(f"Error updating page progress: {e}")
            self.status_bar.showMessage("✗ Error updating page progress")
    
    def quick_status_change(self, status):
        """Quick status change buttons with error handling."""
        if not self.current_file_data:
            return
        
        try:
            current_page = self.current_file_data.get("last_page")
            self.update_file_progress(current_page, status)
        except Exception as e:
            print(f"Error in quick status change: {e}")
            self.status_bar.showMessage("✗ Error updating status")
    
    def on_files_changed(self):
        """Handle file system changes."""
        # Debounce rapid changes
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
        
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.refresh_file_list)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.start(2000)  # 2 second delay
    
    def open_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(self, self.file_tracker)
        if dialog.exec() == QDialog.Accepted:
            # Restart file watcher if folders changed
            if self.file_watcher:
                self.file_watcher.stop_watching()
                self.file_watcher.wait()
            
            self.setup_file_watcher()
            self.refresh_file_list()
    
    def closeEvent(self, event):
        """Handle application close."""
        if self.file_watcher:
            self.file_watcher.stop_watching()
            self.file_watcher.wait()
        
        self.file_tracker.save_data()
        event.accept()


def main():
    """Main application entry point with error handling."""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("PDF/DOCX File Manager")
        app.setApplicationVersion("1.0")
        app.setOrganizationName("FileManager")
        
        # Set application icon (if available)
        # app.setWindowIcon(QIcon("icon.ico"))
        
        # Create and show main window
        window = MainWindow()
        window.show()
        
        # Setup exception handling
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            print(f"Uncaught exception: {exc_type.__name__}: {exc_value}")
            
            # Try to save data before crashing
            try:
                if hasattr(window, 'file_tracker'):
                    window.file_tracker.save_data()
            except:
                pass
        
        sys.excepthook = handle_exception
        
        return app.exec()
        
    except Exception as e:
        print(f"Fatal error starting application: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())