"""Sound library list widget.

Displays sounds in a styled table with sorting, filtering,
context menus, and keyboard shortcut badges.
"""

import logging
import os
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QColor, QFont, QAction, QPainter, QPen, QKeyEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QWidget, QStyledItemDelegate, QStyle,
    QSlider, QHBoxLayout, QLabel
)

from soundpulse.models.sound_item import SoundItem

logger = logging.getLogger(__name__)

# Column indices
COL_TITLE = 0
COL_HOTKEY = 1
COL_DURATION = 2
COL_VOLUME = 3

COLUMN_HEADERS = ["Title", "Hotkey", "Duration", "Volume"]


class BadgeDelegate(QStyledItemDelegate):
    """Draws flat matte badges for Hotkey and Category columns."""
    
    def paint(self, painter: QPainter, option, index) -> None:
        text = index.data(Qt.DisplayRole)
        if not text or text == "—":
            super().paint(painter, option, index)
            return
            
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Determine colors based on column
        if index.column() == COL_HOTKEY:
            bg_color = QColor("#495057")  # Clean dark slate for hotkeys
            text_color = QColor("#ffffff")
            
        # Draw the standard background (respecting QSS selection, hover, and alternate rows)
        # by initializing a fresh option and clearing the text.
        from PySide6.QtWidgets import QStyleOptionViewItem
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        super().paint(painter, opt, index)
            
        # Draw badge rect
        rect = option.rect
        # Center horizontally and vertically
        font_metrics = option.fontMetrics
        text_width = font_metrics.horizontalAdvance(text)
        text_height = font_metrics.height()
        
        badge_width = text_width + 16
        badge_height = text_height + 8
        
        x = rect.x() + (rect.width() - badge_width) // 2
        y = rect.y() + (rect.height() - badge_height) // 2
        
        badge_rect = QRect(x, y, badge_width, badge_height)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(badge_rect, 4, 4)
        
        # Draw text
        painter.setPen(text_color)
        painter.drawText(badge_rect, Qt.AlignCenter, text)
        
        painter.restore()


class VolumeCellWidget(QWidget):
    """Inline volume slider for a table row."""
    volume_changed = Signal(str, float) # sound_id, new_volume
    
    def __init__(self, sound_id: str, current_vol: float, parent=None):
        super().__init__(parent)
        self.sound_id = sound_id
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(current_vol * 100))
        self.slider.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal { background: #E0E0E0; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #4F46E5; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
            QSlider::sub-page:horizontal { background: #4F46E5; border-radius: 2px; }
        """)
        
        self.pct_label = QLabel(f"{int(current_vol * 100)}%")
        self.pct_label.setFixedWidth(35)
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pct_label.setStyleSheet("color: #1E1E2E; font-size: 12px; background: transparent;")
        
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.pct_label)
        
        self.slider.valueChanged.connect(self._on_changed)
        
    def _on_changed(self, val: int):
        self.pct_label.setText(f"{val}%")
        self.volume_changed.emit(self.sound_id, val / 100.0)


class SoundListWidget(QTableWidget):
    """Table widget displaying the sound library.
    
    Signals:
        sound_play_requested(SoundItem): Double-click or Enter to play
        sound_edit_requested(SoundItem): Right-click > Edit
        sound_delete_requested(str): Right-click > Delete (sound_id)
        sound_hotkey_requested(SoundItem): Right-click > Set Hotkey
        sound_trim_requested(SoundItem): Right-click > Trim Audio
        sound_selected(SoundItem): Single click selection
    """
    
    sound_play_requested = Signal(object)   # SoundItem
    sound_edit_requested = Signal(object)   # SoundItem
    sound_rename_requested = Signal(object) # SoundItem
    sound_delete_requested = Signal(str)    # sound_id
    sound_hotkey_requested = Signal(object) # SoundItem
    sound_trim_requested = Signal(object)   # SoundItem
    sound_selected = Signal(object)         # SoundItem
    sound_volume_changed = Signal(object)   # SoundItem
    files_dropped = Signal(list)            # List[str]
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(0, len(COLUMN_HEADERS), parent)
        
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._sounds: List[SoundItem] = []
        self._filtered_sounds: List[SoundItem] = []
        self._playing_id: Optional[str] = None
        
        self._setup_table()
    
    def _setup_table(self) -> None:
        """Configure table appearance and behavior."""
        self.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.cellDoubleClicked.connect(self._on_double_click)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        
        # Column sizing
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_HOTKEY, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_DURATION, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_VOLUME, QHeaderView.Fixed)
        self.setColumnWidth(COL_HOTKEY, 120)
        self.setColumnWidth(COL_DURATION, 100)
        self.setColumnWidth(COL_VOLUME, 180)
        
        # Delegates
        self._badge_delegate = BadgeDelegate(self)
        self.setItemDelegateForColumn(COL_HOTKEY, self._badge_delegate)
        
        # Styling
        self.setStyleSheet("""
            QTableWidget {
                background-color: #0a0c10;
                background-color: #FFFFFF;
                color: #000000;
                gridline-color: #CCCCCC;
                border: none;
                alternate-background-color: #F8F8F8;
            }
            QTableWidget::item {
                padding: 4px;
                border-bottom: 1px solid #E0E0E0;
            }
            QTableWidget::item:selected {
                background-color: #E2E8F0;
                color: #1E1E2E;
            }
            QTableWidget::item:focus {
                outline: none;
                border: none;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                color: #333333;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #CCCCCC;
                border-right: 1px solid #E0E0E0;
                font-weight: 600;
            }
            QScrollBar:vertical {
                background: #F0F0F0;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #CCCCCC;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #AAAAAA;
            }
        """)
    
    def set_sounds(self, sounds: List[SoundItem]) -> None:
        """Set the full sound list and refresh display."""
        self._sounds = list(sounds)
        self._filtered_sounds = list(sounds)
        self._refresh_table()
    
    def add_sound(self, sound: SoundItem) -> None:
        """Add a single sound and refresh."""
        self._sounds.append(sound)
        self._filtered_sounds.append(sound)
        self._refresh_table()
    
    def remove_sound(self, sound_id: str) -> None:
        """Remove a sound by ID."""
        self._sounds = [s for s in self._sounds if s.id != sound_id]
        self._filtered_sounds = [s for s in self._filtered_sounds if s.id != sound_id]
        self._refresh_table()
    
    def update_sound(self, sound: SoundItem) -> None:
        """Update a sound in the list."""
        for i, s in enumerate(self._sounds):
            if s.id == sound.id:
                self._sounds[i] = sound
                break
        for i, s in enumerate(self._filtered_sounds):
            if s.id == sound.id:
                self._filtered_sounds[i] = sound
                break
        self._refresh_table()
    
    def filter_sounds(self, query: str) -> None:
        """Filter displayed sounds by search query."""
        if not query:
            self._filtered_sounds = list(self._sounds)
        else:
            q = query.lower()
            self._filtered_sounds = [
                s for s in self._sounds
                if q in s.title.lower()
            ]
        self._refresh_table()
    
    def highlight_playing(self, sound_id: Optional[str]) -> None:
        """Highlight the currently playing sound and select its row."""
        old_playing_id = self._playing_id
        self._playing_id = sound_id
        
        for row in range(self.rowCount()):
            item = self.item(row, COL_TITLE)
            if not item:
                continue
                
            row_sound_id = item.data(Qt.UserRole)
            
            # Reset old playing item
            if row_sound_id == old_playing_id and old_playing_id != sound_id:
                item.setFont(QFont()) # Default font
                item.setData(Qt.ForegroundRole, None) # Clear override to inherit QSS
                    
            # Highlight new playing item
            if row_sound_id == sound_id:
                item.setForeground(QColor("#4F46E5"))
                item.setFont(QFont("Segoe UI", 13, QFont.Bold))
                
                # Select the currently playing row accurately
                self.setCurrentCell(row, COL_TITLE)
    
    def get_selected_sound(self) -> Optional[SoundItem]:
        """Get the currently selected sound."""
        row = self.currentRow()
        if row < 0:
            return None
            
        item = self.item(row, COL_TITLE)
        if not item:
            return None
            
        sound_id = item.data(Qt.UserRole)
        for s in self._sounds:
            if s.id == sound_id:
                return s
        return None
    
    def _on_volume_changed(self, sound_id: str, new_volume: float) -> None:
        """Handle inline volume slider change."""
        for sound in self._sounds:
            if sound.id == sound_id:
                sound.volume = new_volume
                self.sound_volume_changed.emit(sound)
                break

    def _refresh_table(self) -> None:
        """Rebuild table rows from filtered sounds."""
        self.setSortingEnabled(False)
        self.setRowCount(len(self._filtered_sounds))
        
        for row, sound in enumerate(self._filtered_sounds):
            # Title
            title_item = QTableWidgetItem(sound.title)
            title_item.setData(Qt.UserRole, sound.id)
            if sound.id == self._playing_id:
                title_item.setForeground(QColor("#4F46E5"))
                title_item.setFont(QFont("Segoe UI", 13, QFont.Bold))
            self.setItem(row, COL_TITLE, title_item)
            
            # Hotkey badge
            hotkey_text = sound.hotkey_display()
            hotkey_item = QTableWidgetItem(hotkey_text if hotkey_text else "—")
            hotkey_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, COL_HOTKEY, hotkey_item)
            
            # Duration
            dur_item = QTableWidgetItem(sound.format_duration())
            dur_item.setTextAlignment(Qt.AlignCenter)
            dur_item.setForeground(QColor("#666666"))
            self.setItem(row, COL_DURATION, dur_item)
            
            # Volume Slider
            vol_item = QTableWidgetItem()
            vol_item.setData(Qt.UserRole, sound.volume) # For sorting
            self.setItem(row, COL_VOLUME, vol_item)
            
            vol_widget = VolumeCellWidget(sound.id, sound.volume, self)
            vol_widget.volume_changed.connect(self._on_volume_changed)
            self.setCellWidget(row, COL_VOLUME, vol_widget)
            
            self.setRowHeight(row, 46)
        
        self.setSortingEnabled(True)
    
    def _on_double_click(self, row: int, col: int) -> None:
        item = self.item(row, COL_TITLE)
        if not item:
            return
        sound_id = item.data(Qt.UserRole)
        for s in self._sounds:
            if s.id == sound_id:
                self.sound_play_requested.emit(s)
                break
    
    def _on_selection_changed(self) -> None:
        sound = self.get_selected_sound()
        if sound:
            self.sound_selected.emit(sound)
    
    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0:
            return
        
        item = self.item(row, COL_TITLE)
        if not item:
            return
            
        sound_id = item.data(Qt.UserRole)
        sound = next((s for s in self._sounds if s.id == sound_id), None)
        if not sound:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
            }
            QMenu::item {
                padding: 6px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #E5F1FB;
                color: #000000;
            }
        """)
        
        play_action = menu.addAction("\u25B6  Play")
        play_action.triggered.connect(lambda: self.sound_play_requested.emit(sound))
        
        menu.addSeparator()
        
        rename_action = menu.addAction("\u270E  Rename")
        rename_action.triggered.connect(lambda: self.sound_rename_requested.emit(sound))
        
        hotkey_action = menu.addAction("\u2328  Set Hotkey")
        hotkey_action.triggered.connect(lambda: self.sound_hotkey_requested.emit(sound))
        
        trim_action = menu.addAction("\u2702  Trim Audio")
        trim_action.triggered.connect(lambda: self.sound_trim_requested.emit(sound))
        
        menu.addSeparator()
        
        delete_action = menu.addAction("\U0001F5D1  Delete")
        delete_action.triggered.connect(lambda: self.sound_delete_requested.emit(sound.id))
        
        menu.exec(self.viewport().mapToGlobal(pos))
        
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard events like deleting sounds."""
        if event.key() == Qt.Key_Delete:
            sound = self.get_selected_sound()
            if sound:
                self.sound_delete_requested.emit(sound.id)
            return
        elif event.key() == Qt.Key_F2:
            sound = self.get_selected_sound()
            if sound:
                self.sound_rename_requested.emit(sound)
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)
            
    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
