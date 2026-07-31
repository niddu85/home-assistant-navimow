# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Unofficial Home Assistant custom integration (`custom_components/navimow`) for Segway Navimow robotic lawn mowers. It talks to Segway's Navimow OpenAPI (REST) and MQTT broker directly — there is no local device protocol. `iot_class` is `cloud_polling`.

There is no test suite, linter config, or build step in this repo. Validation happens through two GitHub Actions that run on push/PR:
- `.github/workflows/hassfest.yml` — validates the integration against Home Assistant's `hassfest` schema (manifest correctness, valid platforms, translations, etc.)
- `.github/workflows/hacs.yml` — validates HACS repository requirements

When making changes, mentally check them against what `hassfest` validates (valid `manifest.json`, matching `domain`, present `translations/en.json`, etc.) since there's no local way to run it.

## Architecture

### Data flow: REST + MQTT dual-path

`coordinator.py` (`NavimowDataUpdateCoordinator`, a `DataUpdateCoordinator`) is the central piece all entities read from via `self.coordinator.data[device_id]`:

- **REST polling** every 30s (`update_interval`) via `_async_update_data`, calling `api.async_get_all_vehicles_status`. This is the baseline/fallback data source.
- **MQTT real-time updates** via a `paho-mqtt` WebSocket client set up in `async_setup_mqtt` → `_async_connect_mqtt` → `_connect_mqtt` (runs in an executor job since paho-mqtt is blocking/sync). Incoming messages are dispatched back onto the HA event loop via `hass.add_job(self._handle_mqtt_payload, ...)` and merged into `self.data` in place, then pushed to entities with `async_set_updated_data`.
- MQTT topics are per-device: `/downlink/vehicle/{device_id}/realtimeDate/{state|event|attributes}`. `_handle_mqtt_payload` branches on the trailing topic segment (`channel`) to decide how to merge the payload into `self.data[device_id]`.

Entities never call the API directly for reads — they only read `self.coordinator.data`. Writes (commands) go through `api.async_send_command` from the entity, then request a coordinator refresh.

### OAuth token lifecycle

Two independent token-refresh paths exist and must stay in sync, since MQTT and REST both depend on the same access token:

1. **Proactive refresh**: `_async_ensure_valid_token` runs at the start of every `_async_update_data` cycle and before every mower command (`lawn_mower.py`'s `_async_send_command`), refreshing only if the token is within 10s of `_token_expires_at`.
2. **Reactive refresh**: if a REST call returns `TOKEN_EXPIRED` (code `4005` or specific `desc` values — see `api.async_get_all_vehicles_status`), or if MQTT disconnects (`on_disconnect` callback → `_async_refresh_mqtt_credentials_on_disconnect`), the token and/or MQTT credentials are refreshed reactively.

Refreshed tokens are persisted via `hass.config_entries.async_update_entry(self.entry, data={...})`. When you change token-handling logic, keep both the coordinator's REST path and the MQTT client's credentials/headers updated together — an MQTT client left on a stale token will disconnect in a loop.

### Config flow: custom OAuth without HA's OAuth2 helpers

`config_flow.py` implements OAuth manually rather than using `homeassistant.helpers.config_entry_oauth2_flow`:
1. `async_step_user` — asks for an account name (used as the unique ID and title).
2. `async_step_auth` — registers a temporary `HomeAssistantView` at `/api/navimow/callback` (`NavimowCallbackView`) and shows the user Segway's hosted login URL; the user authenticates in a browser and Segway redirects back to that view.
3. The view's `get()` handler receives the `code` query param and re-enters the flow via `hass.config_entries.flow.async_configure(flow_id, user_input={"code": code})`.
4. `async_step_exchange` swaps the code for `access_token`/`refresh_token` at `TOKEN_URL` and creates the config entry.

`CLIENT_ID`/`CLIENT_SECRET`/`TOKEN_URL`/`AUTH_BASE_URL` are fixed in `const.py` — this is the public client used by Segway's own web login, not a per-user secret.

### State mapping

Raw vehicle states from the Segway API (`isDocked`, `isRunning`, `isPaused`, etc.) are not HA states. `lawn_mower.py` defines `RAW_STATE_TO_CANONICAL` to map raw → canonical (`docked`, `mowing`, `paused`, `returning`, `idle`, `error`, `unknown`), then canonical → `LawnMowerActivity`. Error detection also happens independently in `sensor.py`'s `NavimowErrorSensor` (`_ERROR_RAW_STATES`) and in the MQTT `event` channel handler in `coordinator.py` — if you add new raw states or error conditions from the API, update all three places.

### Platform entities

All platform files (`lawn_mower.py`, `sensor.py`, `binary_sensor.py`, `device_tracker.py`) follow the same pattern: `async_setup_entry` reads `coordinator`/`devices` from `hass.data[DOMAIN][entry.entry_id]` (populated in `__init__.py`) and instantiates one entity per device, each a `CoordinatorEntity` subclass reading from `self.coordinator.data[self._id]` and sharing a `DeviceInfo` keyed by `(DOMAIN, device_id)`.

## Working notes

- Some log messages and code comments are in Italian (e.g. `api.py`'s `async_get_mqtt_info` error message, comments in `lawn_mower.py`/`config_flow.py`). Match the existing style of the surrounding file rather than converting everything at once.
- `manifest.json` `version` should be bumped when making user-facing changes, since HACS/hassfest and update tracking rely on it.
