"""Playlist profiles: list, form, create, duplicate, delete and save."""

import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import QFileDialog, QInputDialog, QListWidgetItem, QMessageBox

from config_manager import DEFAULT_BITRATE, DEFAULT_FORMAT, save_config
from worker import LOSSLESS_FORMATS


def new_profile_id():
    return uuid.uuid4().hex[:12]


class ProfilesMixin:
    """Profile handling of MainWindow (see main_window.py)."""

    def _refresh_profiles(self, select_id=None):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        selected_row = -1
        for index, profile in enumerate(self.config.get("profiles", [])):
            item = QListWidgetItem(profile.get("name", "Unnamed profile"))
            item.setData(Qt.ItemDataRole.UserRole, profile["id"])
            self.profile_list.addItem(item)
            if profile["id"] == select_id:
                selected_row = index
        self.profile_list.blockSignals(False)
        if self.profile_list.count():
            self.profile_list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self.current_profile_id = None
            self._clear_form()

    def _current_profile(self):
        for profile in self.config.get("profiles", []):
            if profile["id"] == self.current_profile_id:
                return profile
        return None

    def _profile_selected(self, current, previous=None):
        if current is None:
            return
        self.current_profile_id = current.data(Qt.ItemDataRole.UserRole)
        profile = self._current_profile()
        if not profile:
            return
        self._loading_profile = True
        self.name_edit.setText(profile.get("name", ""))
        self.url_edit.setText(profile.get("url", ""))
        self.destination_edit.setText(profile.get("destination", ""))
        self.threads_spin.setValue(int(profile.get("threads", 1)))
        self._set_combo(self.format_combo, profile.get("format"), DEFAULT_FORMAT)
        self._set_combo(self.bitrate_combo, profile.get("bitrate"), DEFAULT_BITRATE)
        self._loading_profile = False

    def _clear_form(self):
        self._loading_profile = True
        self.name_edit.clear()
        self.url_edit.clear()
        self.destination_edit.clear()
        self.threads_spin.setValue(1)
        self._set_combo(self.format_combo, DEFAULT_FORMAT, DEFAULT_FORMAT)
        self._set_combo(self.bitrate_combo, DEFAULT_BITRATE, DEFAULT_BITRATE)
        self._loading_profile = False

    @staticmethod
    def _set_combo(combo, value, default):
        index = combo.findText(str(value))
        combo.setCurrentIndex(index if index >= 0 else combo.findText(default))

    def _format_changed(self, audio_format):
        # Lossless formats have no bitrate to choose.
        self.bitrate_combo.setEnabled(audio_format not in LOSSLESS_FORMATS)

    def _new_profile(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Download running", "Stop the current download before changing profiles.")
            return
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok:
            return
        name = name.strip() or "New profile"
        profile = {
            "id": new_profile_id(),
            "name": name,
            "url": "",
            "destination": str(Path.home() / "Music" / name),
            "threads": 1,
            "format": DEFAULT_FORMAT,
            "bitrate": DEFAULT_BITRATE,
        }
        self.config.setdefault("profiles", []).append(profile)
        self._persist()
        self._refresh_profiles(profile["id"])

    def _duplicate_profile(self):
        profile = self._current_profile()
        if not profile:
            return
        clone = dict(profile)
        clone["id"] = new_profile_id()
        clone["name"] = profile.get("name", "Profile") + " (copy)"
        self.config["profiles"].append(clone)
        self._persist()
        self._refresh_profiles(clone["id"])

    def _delete_profile(self):
        profile = self._current_profile()
        if not profile:
            return
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete the profile '{profile.get('name', 'Unnamed profile')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.config["profiles"] = [p for p in self.config["profiles"] if p["id"] != profile["id"]]
        self._persist()
        self._refresh_profiles()

    def _browse_destination(self):
        current = self.destination_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select destination folder", current)
        if path:
            self.destination_edit.setText(path)

    def _save_current_profile(self):
        profile = self._current_profile()
        if not profile:
            QMessageBox.information(self, "No profile", "Create a profile before saving settings.")
            return
        profile["name"] = self.name_edit.text().strip() or "Unnamed profile"
        profile["url"] = self.url_edit.text().strip()
        profile["destination"] = self.destination_edit.text().strip()
        profile["threads"] = self.threads_spin.value()
        profile["format"] = self.format_combo.currentText()
        profile["bitrate"] = self.bitrate_combo.currentText()
        self._persist()
        self._refresh_profiles(profile["id"])
        self.statusBar().showMessage("Profile saved.", 4000)

    def _persist(self):
        try:
            save_config(self.config)
        except OSError as exc:
            QMessageBox.critical(self, "Configuration error", f"Could not save configuration:\n{exc}")

    def _validate_profile(self, profile):
        url = profile.get("url", "").strip()
        if not url.startswith("https://open.spotify.com/playlist/") and not url.startswith("https://spotify.link/"):
            QMessageBox.warning(self, "Invalid playlist URL", "Enter a valid Spotify playlist URL in the selected profile.")
            return False
        if not profile.get("destination", "").strip():
            QMessageBox.warning(self, "Missing destination", "Choose a destination folder first.")
            return False
        return True
