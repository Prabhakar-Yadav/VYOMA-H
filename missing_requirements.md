# Vyoma Challenge: Missing Requirements Check
This document highlights the missing technical implementations in the repository compared against the latest official Q&A requirements.

---

## Critical Code Gaps (Must Fix)

### 1. Dynamic ALSA Audio Input Lookup
* **Requirement:** Avoid hardcoded ALSA device indices or relying on Pulse Audio. Implement a dynamic lookup based on soundcard product names or serial numbers.
* **Current Status:** Not Implemented. The repository currently loads static .wav files for tests or expects the client/UI layer to handle base64 encoding. There is no active soundcard device scanning utility.
* **Impact:** The application will fail or crash on the evaluation hardware if the USB microphone's index shifts.
* **Action:** Implement a helper utility (audio_device.py) to parse /proc/asound/cards and dynamically resolve the microphone index by product name.

### 2. Real-Time OS Swap Monitoring
* **Requirement:** The Jetson Nano uses a unified memory architecture; OS and application software compete for the same memory pool. Exceeding physical RAM forces SSD swap thrashing and heavy latency. Real-time swap levels must be monitored to ensure low latency.
* **Current Status:** Not Implemented. The MemoryOrchestrator uses static budget estimates and does not monitor real-time swap memory usage on the host device.
* **Impact:** The confirmed Bhashini memory leak will eventually force SSD swapping, lagging the live demo.
* **Action:** Implement a parser for /proc/meminfo inside gateway.py to trigger warning logs or emergency model evictions if swap usage exceeds 1 GB.

---

## High-Value Feature Gaps (Score Boosters)

### 1. CUPS Printing Integration
* **Requirement:** The jury supports applications that output print requests to a local CUPS print daemon.
* **Current Status:** Not Implemented. The system currently outputs only text/speech.
* **Productization Impact:** Integrating an offline print trigger (e.g., printing pesticide prescriptions or scheme receipts to a thermal receipt printer via lp) will improve the productization score.

### 2. Multi-Language Bhashini Expansion
* **Requirement:** Teams are encouraged to quantize and adapt Bhashini models beyond the basic repo languages (Hindi, Tamil, Malayalam).
* **Current Status:** Not Implemented. Only the baseline three languages are currently supported.
* **Action:** Quantize a fourth language model (e.g., Kannada or Telugu) to ctranslate2 format to show advanced optimization.

---

## Hardware, UI, and Interface Reminders
* **UI Library Compatibility:** The system supports alternative UI libraries provided they can communicate via the SPI protocol with the ILI9341 display controller.
* **UI Permissions:** First-run execution of the UI controller may require sudo permissions.
* **SSD Upgrade Flashing:** Upgrading from SD card to SSD for faster read/write requires running the NVIDIA SDK manager flash process again with the SSD configuration selected.
* **Power Requirements:** Custom battery solutions must provide between 12 and 20 volts (internally regulated). The system requires up to 25 watts of power at peak performance.
* **Logging:** Ensure all diagnostic logs, latency data, captured audio, and images are stored in the /tmp folder to assist with debug evaluation.
