# Changelog

## 0.3.0

A large rework focused on reliability. It fixes entities becoming unavailable after about an hour, fixes the setup flow, and adds the mower position on the map.

### ⚠️ Before you update

- **Home Assistant 2024.11 or later** is now required.
- **If your entities are currently unavailable** with `Session expired. Please remove and re-add the integration` in the logs, you no longer need to remove the integration. After updating, Home Assistant shows a **re-authentication** notification: open it and log in again.
- **The position needs two settings.** The mower does not report GPS coordinates, so the integration calculates them from the dock location and the map rotation. They default to your Home Assistant home location and 0°. Set them from **Settings → Devices & Services → Navimow (Unofficial) → Configure**. See [Position on the map](#position-on-the-map).

### Fixed

- **Entities becoming unavailable after about an hour** ([#6](https://github.com/niddu85/home-assistant-navimow/issues/6)). v0.2.0 sent an empty client secret when refreshing the access token, so every refresh was rejected once the first token expired. Also fixed in the same area:
  - token refreshes are serialized and tokens are refreshed shortly before they expire;
  - an expired session now starts a re-authentication flow instead of requiring you to remove and re-add the integration;
  - if the Navimow servers can't be reached at startup, Home Assistant retries later instead of loading with no entities;
  - fixed the `TypeError: 'NoneType' object can't be awaited` error on every MQTT message.
- **Setup failing after an abandoned attempt** ([#8](https://github.com/niddu85/home-assistant-navimow/issues/8)). The login callback is registered once and protected with an OAuth `state`. The setup page now continues automatically after you log in. A failed or expired login shows an error page instead of an HTTP 500.
- **Real-time updates.** The MQTT connection closes when the integration is unloaded and reconnects with fresh credentials after a disconnection. Reconnects wait at least 60 seconds, because Navimow rate-limits the credentials endpoint.
- **Failed commands.** Start, pause and dock now show an error in Home Assistant when Navimow rejects them, instead of failing silently.
- **Firmware version.** The device page now shows it.
- **Unknown states.** States the integration doesn't recognize are reported as `unknown` instead of `docked`. An offline mower makes its entities unavailable, except the connectivity sensor.
- Removed the deprecated `TrackerEntity` import reported in [#4](https://github.com/niddu85/home-assistant-navimow/issues/4).

### New

- **Position on the map** ([#4](https://github.com/niddu85/home-assistant-navimow/issues/4), [#7](https://github.com/niddu85/home-assistant-navimow/issues/7)). The position tracker updates about every 2 seconds while the mower moves. It also shows:
  - the distance from the dock;
  - the local coordinates;
  - the current mowing zone and mowing progress, when the mower reports them.
- **Re-authentication flow.** When the session expires, log in again from the notification; there is no need to remove the integration.
- **Diagnostics download**, with tokens and locations redacted.
- **Error sensor** listed in the documentation.

### Position on the map

The mower reports its position in meters from the dock, on its own map, through an undocumented MQTT channel. Home Assistant converts it to GPS using two settings:

- **Dock location:** place the pin on the charging dock.
- **Map rotation:** the mower map is usually not aligned with north. With 0° the map is assumed to point north; positive values turn it clockwise around the dock.

To calibrate the rotation, watch the track on the Home Assistant map while the mower is working. Change the rotation until the track matches your lawn; changes apply immediately.

While mowing, the position changes every 2 seconds and each change is stored in the recorder history. To keep the database smaller, you can exclude the `device_tracker` entity from the [recorder](https://www.home-assistant.io/integrations/recorder/).

### Known limitations

- **Mowing specific zones:** not supported by the Navimow API ([#5](https://github.com/niddu85/home-assistant-navimow/issues/5)). You can see which zone the mower is in, but zone IDs don't match the names in the app.
- **Position:** it's only as accurate as the dock location and rotation you set.
- **Commands:** a command accepted by the Navimow cloud may still be ignored by the mower. The mower state shows what actually happens.

### Thanks

Thanks to [@ekvedaras](https://github.com/ekvedaras) for the token refresh analysis in [#9](https://github.com/niddu85/home-assistant-navimow/pull/9), which this release includes. Thanks to [@goindrinkn](https://github.com/goindrinkn) for the detailed report in #8, and to [@MorGoth667](https://github.com/MorGoth667) and everyone who reported and diagnosed #6.

**Full Changelog**: https://github.com/niddu85/home-assistant-navimow/compare/v0.2.0...v0.3.0

## 0.2.0

- HACS support.

## 0.1.0

- Initial release.
