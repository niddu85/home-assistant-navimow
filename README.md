# Segway Navimow Integration for Home Assistant

Unofficial Home Assistant custom component for Segway Navimow robotic lawn mowers. This integration connects your mower using the official Segway OpenAPI, allowing you to monitor status and control basic operations directly from your smart home.

> [!WARNING]
> This integration is currently in **Active Development (Alpha)**. Features may change, and bugs are expected. Use at your own risk.

## ✨ Features

- **Lawn Mower Entity:** Native Home Assistant `lawn_mower` entity support.
- **Control Commands:** Start mowing, pause, and return to dock.
- **Status Monitoring:** Real-time updates on mower state (mowing, docked, paused, error).
- *(Planned)* **Battery Level:** Track battery percentage as a sensor.
- *(Planned)* **Blade Status:** Monitor blade condition.

## 📋 Requirements

- A Segway Navimow robotic lawn mower.
- An active Navimow app account.
- Home Assistant core.

## ⚙️ Installation

### HACS (Recommended - Coming Soon)
*Note: Until the repository is added to the default HACS store, you must add it as a custom repository.*

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** -> click the three dots in the top right -> **Custom repositories**.
3. Repository: `https://github.com/tuo_username/home-assistant-navimow`
4. Category: **Integration**
5. Click **Add**.
6. Search for "Navimow" in HACS, install it, and restart Home Assistant.

### Manual Installation
TODO

## 🛠️ Configuration

Configuration is done completely via the Home Assistant UI (Config Flow).

1. Go to **Settings** -> **Devices & Services** -> **Integrations**.
2. Click **+ Add Integration** and search for **Navimow**.
3. The setup will prompt you to authenticate with your Navimow account.
4. Follow the on-screen instructions to copy the OAuth code/URL.
5. Paste the code into Home Assistant to finalize the connection.

## 🤝 Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue. If you want to contribute code, feel free to open a pull request.

### Development Setup
*(Add notes here on how to set up the dev environment, run tests, etc.)*

## 📜 Disclaimer

This is an unofficial project and is **not** affiliated with, endorsed by, or sponsored by Segway or Navimow. It uses the official OpenAPI provided by Segway, but the implementation is maintained by the community.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
