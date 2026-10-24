# SoundPulse V1.0.0

A modern, high-performance soundboard application for Windows built with Python, PySide6, and PortAudio. SoundPulse enables you to play audio clips directly into voice chats (Discord, Steam, TeamSpeak, Skype, Zoom, and in-game voice) while simultaneously monitoring playback through your headphones without interrupting your microphone.

---

## Features

- **Dual-Stream Audio Routing**:
  - **Broadcast Stream**: Injects your microphone and soundboard clips into a virtual audio cable (such as VB-CABLE) to feed into Discord, games, or streaming software.
  - **Monitor Stream**: Plays soundboard audio directly through your headphones/speakers in real time with near-zero latency.
- **Discord AI Noise Suppression (Krisp) Compatibility**:
  - Integrated peak gain normalization (-2.0 dBFS) ensures soundboard audio carries sufficient energy.
  - Speech frequency band alignment (300 Hz – 3400 Hz) prevents Krisp and WebRTC echo cancellation from misidentifying non-speech memes as background noise.
  - Continuous mic stream preservation keeps Discord's Voice Activity Detection (VAD) open during audio playback.
- **Real-Time File Synchronization**:
  - Built-in `QFileSystemWatcher` continuously monitors the `sounds/` directory.
  - Adding or deleting audio files in File Explorer updates the library instantly without requiring an app restart.
  - One-click **"Open Sounds Folder"** button opens the folder directly in Windows Explorer.
- **Global Hotkeys & Kill Switch**:
  - Assign global hotkeys to individual sounds to trigger clips even when playing full-screen games.
  - Configurable **Panic / Stop Hotkey** (Kill Switch) instantly halts soundboard playback while preserving active microphone passthrough.
- **Modern Graphical User Interface**:
  - Clean light interface built with PySide6 (Qt).
  - Audio waveform visualization with interactive scrubbing and timeline display.
  - Independent volume sliders for Monitor and Broadcast outputs.
  - Fast search and filtering for large sound collections.
- **Wide Format Support**:
  - Plays MP3, WAV, FLAC, OGG, and M4A audio files.
  - Fast decoding powered by `miniaudio` and optional high-fidelity resampling with `libsoxr`.

---

## Requirements

- **Operating System**: Windows 10 or Windows 11 (64-bit)
- **Python**: Python 3.10 or higher
- **Virtual Audio Cable** *(Recommended for voice chats)*:
  - Install [VB-CABLE](https://vb-audio.com/Cable/) or an equivalent virtual audio driver to route audio into Discord or game voice chats.

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Daniil-02/soundpad.git
   cd soundpad
   ```

2. **Create and activate a virtual environment** *(optional but recommended)*:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Running the Application

Launch SoundPulse directly with Python:

```bash
python main.py
```

---

## Audio Setup Guide for Discord & Games

To broadcast sounds into Discord, TeamSpeak, or games:

1. **Configure SoundPulse (Settings -> Audio Devices)**:
   - **Microphone**: Select your physical microphone.
   - **Monitor Output**: Select your headphones/speakers (where you want to hear audio).
   - **Broadcast Output**: Select **CABLE Input (VB-Audio Virtual Cable)**.
2. **Configure Discord / Game Settings**:
   - Set your **Input Device** (Microphone) in Discord to **CABLE Output (VB-Audio Virtual Cable)**.
   - Set your **Output Device** in Discord to your normal headphones.
3. Now whenever you speak or play a sound, it will flow seamlessly into Discord.

---

## Adding Sounds

- Place your `.mp3`, `.wav`, `.ogg`, or `.flac` files directly into the `sounds/` folder in the project root.
- Alternatively, click the **"📂 Open Sounds Folder"** button in the top toolbar to reveal the directory in Windows Explorer and drag-and-drop your audio files.
- The UI will immediately detect new sounds and display them in the soundboard list.

---

## Project Structure

```text
soundpad/
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
├── README.md                   # Project documentation
├── .gitignore                  # Git ignore rules
├── sounds/                     # Soundboard audio files directory
└── soundpulse/                 # Core application package
    ├── __init__.py
    ├── audio/                  # Audio engine, decoding, resampling, device management
    │   ├── decoder.py
    │   ├── device_manager.py
    │   ├── engine.py
    │   └── resampler.py
    ├── config/                 # Settings and persistent configuration
    │   └── settings.py
    ├── hotkeys/                # Global keybind listener & panic switch
    │   └── global_hotkey.py
    ├── models/                 # Data models (SoundItem)
    │   └── sound_item.py
    └── ui/                     # PySide6 user interface components
        ├── components.py
        ├── hotkey_editor.py
        ├── main_window.py
        ├── playback_bar.py
        ├── search_bar.py
        ├── settings_dialog.py
        ├── sound_list.py
        ├── volume_controls.py
        └── waveform_widget.py
```

---

## License

This project is open-source and available under the [MIT License](LICENSE).
