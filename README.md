# SoundPulse V1.0.0

A modern, low-latency soundboard for Windows built with Python and PySide6. Play audio memes and clips directly into Discord, Steam, and in-game voice chats while speaking through your microphone, with real-time headphone monitoring and AI noise suppression (Krisp) compatibility.

---

## 🚀 Quick Start (Choose How to Run)

### Option 1: Standalone App (No Python Required — Recommended)
1. Go to [**Releases**](https://github.com/Daniil-02/soundpad/releases) and download the latest `SoundPulse-v1.0.0-Windows.zip`.
2. Extract the archive.
3. Launch `SoundPulse.exe` — that's it!

### Option 2: Run from Source (`main.py`)
1. **Clone the repository**:
   ```bash
   git clone https://github.com/Daniil-02/soundpad.git
   cd soundpad
   ```
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the application**:
   ```bash
   python main.py
   ```

---

## 🎧 Audio Setup for Discord & Games

To route audio into voice chats, use a virtual audio cable such as [VB-CABLE](https://vb-audio.com/Cable/):

1. **In SoundPulse (Settings -> Audio Devices)**:
   - **Microphone**: Your physical microphone.
   - **Monitor Output**: Your headphones / speakers.
   - **Broadcast Output**: `CABLE Input (VB-Audio Virtual Cable)`.
2. **In Discord / Games**:
   - **Input Device**: `CABLE Output (VB-Audio Virtual Cable)`.
   - **Output Device**: Your regular headphones.

---

## ✨ Features

- **Simultaneous Mic + Sound Playback**: Injects sounds into voice chat without interrupting your microphone.
- **Discord & Krisp Compatible**: Normalized gain (-2.0 dBFS) and speech-band tuning prevent AI noise suppression from filtering out audio memes.
- **Real-Time Folder Sync**: Drop `.mp3`, `.wav`, `.ogg`, or `.flac` files into the `sounds/` folder (or click **"📂 Open Sounds Folder"** in the app) and they appear immediately.
- **Global Keybinds & Kill Switch**: Assign hotkeys to sounds and configure an emergency Stop keybind that immediately silences audio.
- **Audio Waveform**: Interactive timeline with click-to-seek playback.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
