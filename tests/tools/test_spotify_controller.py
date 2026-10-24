from __future__ import annotations

import threading
import time

import pytest
from spotipy.exceptions import SpotifyException

import ragstream.tools.spotify.spotify_controller as spotify_module
from ragstream.tools.spotify.spotify_controller import (
    SpotifyController,
    SpotifyQueuePartialFailure,
    SpotifyDeviceUnavailable,
    normalize_spotify_resource,
)


class FakeSpotifyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.transfer_event = threading.Event()
        self.fail_start_once = False
        self.device_items = [
            {
                "id": "phone-1",
                "name": "Phone",
                "type": "Smartphone",
                "is_active": True,
                "is_restricted": False,
            }
        ]
        self.pages: dict[int, dict] = {}

    def devices(self) -> dict:
        self.calls.append(("devices", {}))
        return {"devices": list(self.device_items)}

    def playlist_items(
        self,
        playlist_id: str,
        *,
        limit: int,
        offset: int,
    ) -> dict:
        self.calls.append(
            (
                "playlist_items",
                {
                    "playlist_id": playlist_id,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        return self.pages[offset]

    def start_playback(self, **kwargs) -> None:
        self.calls.append(("start_playback", kwargs))
        if self.fail_start_once:
            self.fail_start_once = False
            raise SpotifyException(404, -1, "No active device found")

    def shuffle(self, state: bool, **kwargs) -> None:
        self.calls.append(("shuffle", {"state": state, **kwargs}))

    def repeat(self, state: str, **kwargs) -> None:
        self.calls.append(("repeat", {"state": state, **kwargs}))

    def add_to_queue(self, uri: str, **kwargs) -> None:
        self.calls.append(("add_to_queue", {"uri": uri, **kwargs}))

    def pause_playback(self, **kwargs) -> None:
        self.calls.append(("pause_playback", kwargs))

    def transfer_playback(
        self,
        device_id: str,
        *,
        force_play: bool,
    ) -> None:
        self.calls.append(
            (
                "transfer_playback",
                {
                    "device_id": device_id,
                    "force_play": force_play,
                },
            )
        )
        self.transfer_event.set()


def test_normalize_spotify_url() -> None:
    value = "https://open.spotify.com/track/1234567890?si=abc"
    assert normalize_spotify_resource(value) == "spotify:track:1234567890"


def test_device_ready_and_playlist_read_both_refresh_device() -> None:
    client = FakeSpotifyClient()
    client.pages = {0: {"items": [], "total": 0, "next": None}}
    controller = SpotifyController(client=client)

    ready = controller.device_ready()
    controller.playlist_tracks("spotify:playlist:parent")

    assert ready["ready"] is True
    assert [name for name, _ in client.calls].count("devices") == 2


def test_playlist_read_does_not_expose_cached_is_active_as_live_state() -> None:
    client = FakeSpotifyClient()
    client.device_items[0]["is_active"] = False
    client.pages = {0: {"items": [], "total": 0, "next": None}}
    controller = SpotifyController(client=client)

    ready = controller.device_ready()
    assert ready["device"]["is_active"] is False

    client.device_items[0]["is_active"] = True
    client.calls.clear()
    playlist = controller.playlist_tracks("spotify:playlist:parent")

    assert "is_active" not in playlist["device"]
    assert [name for name, _ in client.calls].count("devices") == 1

    live = controller.device_ready()
    assert live["device"]["is_active"] is True
    assert [name for name, _ in client.calls].count("devices") == 2


def test_device_check_rejects_missing_connect_target() -> None:
    client = FakeSpotifyClient()
    client.device_items = []
    controller = SpotifyController(client=client)

    with pytest.raises(SpotifyDeviceUnavailable):
        controller.device_ready()


def test_start_stops_before_playback_when_no_device_is_ready() -> None:
    client = FakeSpotifyClient()
    client.device_items = []
    controller = SpotifyController(client=client)

    with pytest.raises(SpotifyDeviceUnavailable):
        controller.start(
            "spotify:playlist:parent",
            "spotify:track:starter",
        )

    assert client.calls == [("devices", {})]


def test_add_queue_stops_before_first_insert_when_no_device_is_ready() -> None:
    client = FakeSpotifyClient()
    client.device_items = []
    controller = SpotifyController(client=client)

    with pytest.raises(SpotifyDeviceUnavailable):
        controller.add_queue(["spotify:track:first"])

    assert client.calls == [("devices", {})]


def test_playlist_tracks_returns_complete_ordered_pages() -> None:
    client = FakeSpotifyClient()
    client.pages = {
        0: {
            "items": [
                {
                    "item": {
                        "name": "Movement I",
                        "artists": [{"name": "Quartet"}],
                        "uri": "spotify:track:one",
                        "type": "track",
                    }
                },
                {
                    "track": {
                        "name": "Movement II",
                        "artists": [{"name": "Quartet"}],
                        "uri": "spotify:track:two",
                        "type": "track",
                    }
                },
            ],
            "total": 3,
            "next": "next-page",
        },
        2: {
            "items": [
                {
                    "item": {
                        "name": "Movement III",
                        "artists": [{"name": "Quartet"}],
                        "uri": "spotify:track:three",
                        "type": "track",
                    }
                }
            ],
            "total": 3,
            "next": None,
        },
    }
    controller = SpotifyController(client=client)

    result = controller.playlist_tracks("spotify:playlist:parent")

    assert result["track_count"] == 3
    assert [item["position"] for item in result["tracks"]] == [1, 2, 3]
    assert [item["uri"] for item in result["tracks"]] == [
        "spotify:track:one",
        "spotify:track:two",
        "spotify:track:three",
    ]
    assert [name for name, _ in client.calls].count("devices") == 1
    playlist_calls = [
        call for call in client.calls if call[0] == "playlist_items"
    ]
    assert [call[1]["offset"] for call in playlist_calls] == [0, 2]


def test_start_refreshes_device_and_starts_before_secondary_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spotify_module,
        "PLAYBACK_SETTINGS_DELAY_SECONDS",
        0.05,
    )

    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)

    result = controller.start(
        "spotify:playlist:parent",
        "spotify:track:starter",
    )

    assert result["action"] == "started"
    assert client.calls == [
        ("devices", {}),
        (
            "start_playback",
            {
                "device_id": "phone-1",
                "context_uri": "spotify:playlist:parent",
                "offset": {"uri": "spotify:track:starter"},
                "position_ms": 0,
            },
        ),
    ]

    time.sleep(0.10)

    assert client.calls[2:] == [
        ("shuffle", {"state": False, "device_id": "phone-1"}),
        ("repeat", {"state": "off", "device_id": "phone-1"}),
    ]


def test_start_accepts_episode_uri_in_playlist_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)
    monkeypatch.setattr(controller, "_schedule_settings", lambda device_id: None)

    result = controller.start(
        "spotify:playlist:parent",
        "spotify:episode:lecture",
    )

    assert result["starter_track_uri"] == "spotify:episode:lecture"
    assert client.calls == [
        ("devices", {}),
        (
            "start_playback",
            {
                "device_id": "phone-1",
                "context_uri": "spotify:playlist:parent",
                "offset": {"uri": "spotify:episode:lecture"},
                "position_ms": 0,
            },
        ),
    ]


def test_start_rejects_non_track_or_episode_resource() -> None:
    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)

    with pytest.raises(ValueError, match="track or episode"):
        controller.start(
            "spotify:playlist:parent",
            "spotify:artist:not-a-starter",
        )

    assert client.calls == []


def test_start_refreshes_live_device_and_retries_404_once() -> None:
    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)
    controller.device_ready()

    client.device_items = [
        {
            "id": "phone-2",
            "name": "Phone 2",
            "type": "Smartphone",
            "is_active": True,
            "is_restricted": False,
        }
    ]
    client.calls.clear()
    client.fail_start_once = True

    result = controller.start(
        "spotify:playlist:parent",
        "spotify:track:starter",
    )

    assert result["device"] == "Phone 2"
    assert [name for name, _ in client.calls[:4]] == [
        "devices",
        "start_playback",
        "devices",
        "start_playback",
    ]
    assert client.calls[1][1]["device_id"] == "phone-2"
    assert client.calls[3][1]["device_id"] == "phone-2"


def test_add_queue_refreshes_device_and_preserves_track_order() -> None:
    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)

    result = controller.add_queue(
        [
            "spotify:track:first",
            "https://open.spotify.com/track/second?si=test",
        ]
    )

    assert result["action"] == "queued"
    assert result["track_count"] == 2
    assert result["track_uris"] == [
        "spotify:track:first",
        "spotify:track:second",
    ]
    assert client.calls == [
        ("devices", {}),
        ("add_to_queue", {"uri": "spotify:track:first", "device_id": "phone-1"}),
        ("add_to_queue", {"uri": "spotify:track:second", "device_id": "phone-1"}),
    ]


def test_add_queue_reports_partial_progress_without_replaying_prefix() -> None:
    class FailingQueueClient(FakeSpotifyClient):
        def add_to_queue(self, uri: str, **kwargs) -> None:
            super().add_to_queue(uri, **kwargs)
            if uri == "spotify:track:second":
                raise ConnectionError("remote connection closed")

    controller = SpotifyController(client=FailingQueueClient())

    with pytest.raises(SpotifyQueuePartialFailure) as caught:
        controller.add_queue(
            [
                "spotify:track:first",
                "spotify:track:second",
                "spotify:track:third",
            ]
        )

    error = caught.value
    assert error.queued_track_uris == ["spotify:track:first"]
    assert error.failed_track_uri == "spotify:track:second"
    assert error.remaining_track_uris == ["spotify:track:third"]
    assert error.delivery_uncertain is True


def test_add_queue_rejects_non_track_resources() -> None:
    controller = SpotifyController(client=FakeSpotifyClient())

    with pytest.raises(ValueError):
        controller.add_queue(["spotify:playlist:not-a-track"])


def test_pause_and_stop_refresh_live_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spotify_module,
        "KEEPALIVE_INTERVAL_SECONDS",
        60.0,
    )

    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)

    paused = controller.pause()
    stopped = controller.stop()

    assert paused["action"] == "paused"
    assert stopped["action"] == "stopped"
    assert client.calls == [
        ("devices", {}),
        ("pause_playback", {"device_id": "phone-1"}),
        ("devices", {}),
        ("pause_playback", {"device_id": "phone-1"}),
    ]


def test_pause_keepalive_is_silent_and_stop_cancels_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spotify_module,
        "KEEPALIVE_INTERVAL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        spotify_module,
        "KEEPALIVE_MAX_SECONDS",
        0.20,
    )

    client = FakeSpotifyClient()
    controller = SpotifyController(client=client)
    controller.device_ready()
    client.calls.clear()

    controller.pause()
    assert client.transfer_event.wait(timeout=0.20)

    transfers_before_stop = len(
        [call for call in client.calls if call[0] == "transfer_playback"]
    )
    assert transfers_before_stop >= 1
    assert all(
        call[1]["force_play"] is False
        for call in client.calls
        if call[0] == "transfer_playback"
    )

    started = time.monotonic()
    controller.stop()
    elapsed = time.monotonic() - started

    transfers_after_stop = len(
        [call for call in client.calls if call[0] == "transfer_playback"]
    )
    time.sleep(0.04)

    assert elapsed < 0.10
    assert len(
        [call for call in client.calls if call[0] == "transfer_playback"]
    ) == transfers_after_stop
