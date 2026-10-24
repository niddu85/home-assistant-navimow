# Segway Navimow Integration for Home Assistant

<img src="custom_components/navimow/brand/icon.png" alt="Navimow Integration Icon" width="128" height="128" />

Unofficial Home Assistant custom integration for Segway Navimow robotic lawn mowers. This integration connects your mower using the official Segway OpenAPI, allowing you to monitor real-time status and control operations directly from Home Assistant.

> [!WARNING]
> This integration is currently in **Active Development (Alpha)**. Features may change, and bugs are expected. Use at your own risk.

## ✨ Features

### Implemented

- **Lawn Mower Entity:** Full native Home Assistant `lawn_mower` entity
  - Start/resume mowing
  - Pause operation
  - Return to dock
  - Real-time state monitoring (mowing, docked, paused, returning, error)
- **Sensors:**
  - Battery level (percentage)
  - Error (last error reported by the mower, `none` otherwise)

- **Binary Sensors:**
  - Connectivity status (online/offline)

- **Device Tracker:**
  - GPS location tracking with real-time position updates

- **Data Updates:**
  - Polling updates every 30 seconds via REST API
  - Real-time MQTT WebSocket connection for instant state changes
  - Automatic token refresh when access tokens expire
  - Re-authentication prompt when the session can no longer be refreshed

### Architecture

- **OAuth2 Authentication:** Secure account connection via official Navimow OAuth flow
- **Data Coordinator:** Centralized data management with automatic refresh handling
- **MQTT Real-time Updates:** WebSocket-based MQTT for instant device state changes
- **Token Management:** Automatic refresh token handling with persistent storage
- **Diagnostics:** Downloadable diagnostics with tokens and GPS position redacted

## 📋 Requirements

- A Segway Navimow robotic lawn mower with an active account
- Home Assistant 2024.11 or later
- Active internet connection

## ⚙️ Installation

### HACS (Recommended - Coming Soon)

_Note: Until the repository is added to the default HACS store, you must add it as a custom repository._

1. Open HACS in your Home Assistant instance
2. Go to **Integrations** → click the three dots in the top right → **Custom repositories**
3. Repository: `https://github.com/niddu85/home-assistant-navimow`
4. Category: **Integration**
5. Click **Add**
6. Search for "Navimow" in HACS and install it
7. Restart Home Assistant

### Manual Installation

1. Clone or download this repository
2. Copy the `custom_components/navimow` folder to your `custom_components` directory
3. Restart Home Assistant

## 🛠️ Configuration

Configuration is done completely via the Home Assistant UI (Config Flow).

1. Go to **Settings** → **Devices & Services** → **Integrations**
2. Click **+ Add Integration** and search for **Navimow**
3. Enter a name for the account
4. A browser window will open on the Navimow login page
5. After logging in, Home Assistant completes the setup automatically

The login redirects back to `<your Home Assistant URL>/api/navimow/callback`, so the browser must be able to reach Home Assistant at its configured URL (**Settings** → **System** → **Network**).

## 📱 Available Entities

### Lawn Mower

- Entity ID: `lawn_mower.{device_name}`
- States: `docked`, `mowing`, `paused`, `returning`, `error` (an idle mower is reported as `docked`)
- Commands: `start_mowing()`, `pause()`, `dock()`
- Unavailable while the mower is offline

### Sensor

- Entity ID: `sensor.{device_name}_battery`
- Value: Battery percentage (0-100%)
- Unit: %

- Entity ID: `sensor.{device_name}_error`
- Value: error code reported by the mower, or `none`

### Binary Sensor

- Entity ID: `binary_sensor.{device_name}_connectivity`
- On: Device is online
- Off: Device is offline

### Device Tracker

- Entity ID: `device_tracker.{device_name}_position`
- Attributes: `latitude`, `longitude`

## 🔄 How It Works

1. **OAuth Authentication:** Securely authenticates with Segway servers using OAuth2
2. **REST Polling:** Fetches device status every 30 seconds
3. **MQTT Streaming:** Maintains a WebSocket connection for real-time updates, reconnecting with fresh credentials (and increasing delays) when it drops
4. **Token Management:** Refreshes the token shortly before it expires; if the refresh token is rejected, Home Assistant asks you to log in again
5. **Entity Creation:** Creates Home Assistant entities for each connected device

## 🐛 Troubleshooting

### Integration not showing up

- Restart Home Assistant after installation
- Clear browser cache if stuck on setup page

### Entities not updating

- Check that your internet connection is stable
- Verify the Navimow app still works on your phone
- Check Home Assistant logs for errors: `Settings` → `System` → `Logs`

### Authentication errors

- Ensure your Navimow account is still active
- If Home Assistant shows a **Reconfigure** / re-authentication notification for Navimow, follow it and log in again
- If the login page does not return to Home Assistant, check the Home Assistant URL in **Settings** → **System** → **Network**

## 🧪 Development

```bash
pip install -r requirements_test.txt
pytest
```

The Home Assistant test harness does not install on native Windows: use WSL or Linux.

## 🤝 Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue or submit a pull request.

## 📜 Disclaimer

This is an **unofficial** project and is **not** affiliated with, endorsed by, or sponsored by Segway or Navimow. It uses the official OpenAPI provided by Segway, but the implementation is maintained by the community.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📚 References

- [Segway Navimow Official App](https://www.segway.com/navimow/)
- [Home Assistant Lawn Mower Component](https://www.home-assistant.io/integrations/lawn_mower/)
- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
