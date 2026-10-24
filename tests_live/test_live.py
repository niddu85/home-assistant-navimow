"""Live tests against the real Navimow cloud (read-only unless enabled)."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from custom_components.navimow.api import NavimowApiClient
from custom_components.navimow.const import OFFLINE_STATES
from custom_components.navimow.lawn_mower import RAW_STATE_TO_ACTIVITY
from custom_components.navimow.mqtt import NavimowMqttClient, _close_client, _start_client

from .conftest import capture

MQTT_WAIT = int(os.environ.get("NAVIMOW_LIVE_MQTT_WAIT", "30"))
COMMANDS_ENABLED = os.environ.get("NAVIMOW_LIVE_COMMANDS") == "1"
MOVE_ENABLED = os.environ.get("NAVIMOW_LIVE_MOVE") == "1"
MOW_SECONDS = int(os.environ.get("NAVIMOW_LIVE_MOW_SECONDS", "90"))
RETURN_SECONDS = int(os.environ.get("NAVIMOW_LIVE_RETURN_SECONDS", "120"))
STATUS_INTERVAL = 30
MIN_BATTERY = 30


async def _statuses(api: NavimowApiClient) -> dict:
    devices = await api.async_get_devices()
    return await api.async_get_vehicles_status([d["id"] for d in devices])


def _battery(status: dict) -> float | None:
    capacity = status.get("capacityRemaining")
    if isinstance(capacity, list) and capacity:
        return capacity[0].get("rawValue")
    return None


@asynccontextmanager
async def _mqtt_listener(
    api: NavimowApiClient, device_ids: list[str]
) -> AsyncIterator[SimpleNamespace]:
    """Connect with the integration's MQTT client code and collect messages."""
    loop = asyncio.get_running_loop()
    started = time.monotonic()
    connected = asyncio.Event()
    result = SimpleNamespace(messages=[], suback_codes=[], disconnected=asyncio.Event())

    def on_message(topic: str, payload: dict) -> None:
        elapsed = time.monotonic() - started
        result.messages.append({"t": round(elapsed, 1), "topic": topic, "payload": payload})
        print(f"[{elapsed:5.0f}s] MQTT {topic.rsplit('/', 1)[-1]}: {payload}")

    mqtt_client = NavimowMqttClient(
        SimpleNamespace(loop=loop), None, api, device_ids, on_message
    )
    # Reconnecting needs a config entry: here only record that it would happen
    mqtt_client._async_schedule_reconnect = lambda client: result.disconnected.set()

    # Fetched only once: the endpoint rejects calls less than a minute apart
    info = await api.async_get_mqtt_info()
    capture("mqtt_userInfo", info)
    print(f"\nmqtt info fields: {sorted(info)}")
    token = await api.async_get_access_token()
    client, hostname = await asyncio.to_thread(mqtt_client._create_client, info, token)
    on_connect = client.on_connect

    def _on_connect(*args):
        on_connect(*args)
        if not args[3].is_failure:
            loop.call_soon_threadsafe(connected.set)

    client.on_connect = _on_connect
    client.on_subscribe = lambda c, u, mid, codes, props: result.suback_codes.extend(codes)
    mqtt_client._client = client
    await asyncio.to_thread(_start_client, client, hostname)
    try:
        await asyncio.wait(
            [
                asyncio.create_task(connected.wait()),
                asyncio.create_task(result.disconnected.wait()),
            ],
            timeout=20,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert connected.is_set(), "MQTT connection refused or timed out"
        yield result
    finally:
        await asyncio.to_thread(_close_client, client)


async def test_token_refresh(api: NavimowApiClient) -> None:
    old_access, old_refresh = api._access_token, api._refresh_token
    await api._async_refresh_token(rejected_token=old_access)

    assert api._access_token != old_access
    print(f"\nrefresh token rotated: {api._refresh_token != old_refresh}")
    print(f"token lifetime: {api._expires_at - time.time():.0f}s")
    # The new token must work
    await api.async_get_devices()


async def test_devices(api: NavimowApiClient) -> None:
    devices = await api.async_get_devices()
    capture("authList_devices", devices)

    assert devices, "no mower linked to the account"
    for device in devices:
        assert device.get("id")
        print(f"\ndevice fields: {sorted(device)}")


async def test_vehicle_status(api: NavimowApiClient) -> None:
    statuses = await _statuses(api)
    capture("getVehicleStatus", statuses)

    assert statuses
    for device_id, status in statuses.items():
        print(f"\n{device_id} status fields: {sorted(status)}")
        state = status.get("vehicleState")
        print(f"vehicleState: {state!r}, online: {status.get('online')!r}")
        assert state in RAW_STATE_TO_ACTIVITY or state in OFFLINE_STATES, (
            f"vehicleState {state!r} is not mapped"
        )

        capacity = status.get("capacityRemaining")
        print(f"capacityRemaining: {capacity!r}")
        assert isinstance(capacity, list)
        assert isinstance(capacity[0].get("rawValue"), int | float)
        assert 0 <= capacity[0]["rawValue"] <= 100

        position = status.get("position")
        fields = sorted(position) if isinstance(position, dict) else position
        print(f"position fields: {fields!r}")


async def test_mqtt_connect_and_receive(api: NavimowApiClient) -> None:
    device_ids = list(await _statuses(api))
    async with _mqtt_listener(api, device_ids) as mqtt:
        print(f"connected, waiting {MQTT_WAIT}s for messages")
        await asyncio.sleep(MQTT_WAIT)
        assert not mqtt.disconnected.is_set(), "MQTT disconnected while waiting"

    print(f"subscription results: {[str(code) for code in mqtt.suback_codes]}")
    assert len(mqtt.suback_codes) == 3 * len(device_ids), "missing SUBACKs"
    assert not any(code.is_failure for code in mqtt.suback_codes), "subscription refused"
    capture("mqtt_messages", mqtt.messages)
    print(f"messages received: {len(mqtt.messages)}")


@pytest.mark.skipif(not COMMANDS_ENABLED, reason="set NAVIMOW_LIVE_COMMANDS=1 to send commands")
async def test_command_without_side_effects(api: NavimowApiClient) -> None:
    """Send a command that does not change what the mower is doing."""
    statuses = await _statuses(api)
    device_id, status = next(iter(statuses.items()))
    state = status.get("vehicleState")

    if state == "isDocked":
        await api.async_send_command(device_id, "action.devices.commands.Dock")
    elif state == "isPaused":
        await api.async_send_command(
            device_id, "action.devices.commands.PauseUnpause", {"on": False}
        )
    else:
        pytest.skip(f"no harmless command for state {state!r}")

    await asyncio.sleep(5)
    after = (await _statuses(api))[device_id].get("vehicleState")
    print(f"\nstate before: {state!r}, after: {after!r}")
    assert after == state


@pytest.mark.skipif(not MOVE_ENABLED, reason="set NAVIMOW_LIVE_MOVE=1 to let the mower move")
async def test_mowing_cycle(api: NavimowApiClient) -> None:
    """Start mowing, record status and MQTT traffic, then send the mower home.

    The dock command is always sent, even if something fails midway.
    """
    statuses = await _statuses(api)
    device_id, status = next(iter(statuses.items()))
    if status.get("vehicleState") != "isDocked":
        pytest.skip(f"mower must start docked, it is {status.get('vehicleState')!r}")
    if (_battery(status) or 0) < MIN_BATTERY:
        pytest.skip(f"battery too low: {_battery(status)}%")

    started = time.monotonic()
    rest_timeline: list[dict] = []

    async def poll_rest() -> dict:
        current = (await api.async_get_vehicles_status([device_id]))[device_id]
        elapsed = time.monotonic() - started
        rest_timeline.append({"t": round(elapsed, 1), "status": current})
        print(
            f"[{elapsed:5.0f}s] REST {current.get('vehicleState')} "
            f"battery={_battery(current)} position={current.get('position')!r} "
            f"extra={sorted(set(current) - {'id', 'vehicleState', 'capacityRemaining', 'descriptiveCapacityRemaining'})}"
        )
        return current

    async with _mqtt_listener(api, [device_id]) as mqtt:
        try:
            await api.async_send_command(
                device_id, "action.devices.commands.StartStop", {"on": True}
            )
            print(f"[{time.monotonic() - started:5.0f}s] start mowing sent")
            while time.monotonic() - started < MOW_SECONDS:
                await asyncio.sleep(STATUS_INTERVAL)
                await poll_rest()
        finally:
            await api.async_send_command(device_id, "action.devices.commands.Dock")
            print(f"[{time.monotonic() - started:5.0f}s] dock sent")

        return_started = time.monotonic()
        while time.monotonic() - return_started < RETURN_SECONDS:
            await asyncio.sleep(STATUS_INTERVAL)
            await poll_rest()

    capture("mowing_cycle", {"rest": rest_timeline, "mqtt": mqtt.messages})

    states = [entry["status"].get("vehicleState") for entry in rest_timeline]
    mqtt_keys = sorted({key for m in mqtt.messages for key in m["payload"]})
    gps_messages = [
        m for m in mqtt.messages
        if any(k in m["payload"] for k in ("position", "lat", "lng", "latitude", "longitude"))
    ]
    print("\n=== summary ===")
    print(f"REST states: {states}")
    print(f"REST positions: {sum('position' in e['status'] for e in rest_timeline)}")
    print(f"MQTT messages: {len(mqtt.messages)}, payload keys: {mqtt_keys}")
    print(f"MQTT messages with GPS-like keys: {len(gps_messages)}")

    assert any(state not in (None, "isDocked") for state in states), "mower never left the dock"
