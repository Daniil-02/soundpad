"""SoundPulse — Entry Point.

Launches the SoundPulse application with dark theme,
high-DPI scaling, and global exception handling.
"""

import logging
import sys
import traceback

# Configure logging before any imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("SoundPulse")


def exception_hook(exc_type, exc_value, exc_tb):
    """Global exception handler to prevent silent crashes."""
    logger.critical(
        "Unhandled exception:\n" +
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


# Global light theme stylesheet
GLOBAL_STYLESHEET = """
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
    color: #000000;
}
QMainWindow, QDialog {
    background-color: #f0f0f0;
}
"""


def main():
    """Application entry point."""
    # Install global exception hook
    sys.excepthook = exception_hook
    
    # Import PySide6 after logging is configured
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    
    # Enable high-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("SoundPulse")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("SoundPulse")
    
    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    app.setStyle("windowsvista")
    app.setStyleSheet(GLOBAL_STYLESHEET)
    
    # Create and show main window
    from soundpulse.ui.main_window import MainWindow
    
    window = MainWindow()
    window.show()
    
    logger.info("SoundPulse started")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
