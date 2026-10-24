"""Provide the minimal deterministic Spotify Web API boundary for GHOST.

Main class:
    SpotifyController:
        Owns Spotify authentication and the five Spotify operations used by MCP.

Main methods:
    playlist_tracks():
        Cache device readiness and optionally return one playlist's ordered items.
    start():
        Start an exact track inside an exact parent context with minimum latency.
    add_queue():
        Add exact ordered track URIs to Spotify's live queue.
    pause():
        Pause playback and start the silent two-hour Connect keepalive.
    stop():
        End GHOST playback by pausing and cancelling background Spotify activity.

Important notes:
    Spotify Web API has no separate stop/disconnect endpoint. GHOST stop therefore
    means pause playback and terminate its own background activity completely.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyPKCE


KEEPALIVE_INTERVAL_SECONDS = 60.0
KEEPALIVE_MAX_SECONDS = 2 * 60 * 60
PLAYBACK_SETTINGS_DELAY_SECONDS = 15.0


class SpotifyDeviceUnavailable(RuntimeError):
    """Raised when Spotify exposes no controllable Connect device."""

class SpotifyQueuePartialFailure(RuntimeError):
    """Report known queue progress when a multi-track insert stops."""

    def __init__(
        self,
        message: str,
        queued_track_uris: list[str],
        failed_track_uri: str,
        remaining_track_uris: list[str],
        delivery_uncertain: bool,
    ) -> None:
        super().__init__(message)
        self.queued_track_uris = list(queued_track_uris)
        self.failed_track_uri = failed_track_uri
        self.remaining_track_uris = list(remaining_track_uris)
        self.delivery_uncertain = delivery_uncertain



def normalize_spotify_resource(value: str) -> str:
    """Return a canonical Spotify URI for one supported URL or URI."""
    clean = value.strip()
    if clean.startswith("spotify:"):
        parts = clean.split(":")
        if len(parts) == 3 and all(parts):
            return clean
        raise ValueError(f"Invalid Spotify URI: {value}")

    parsed = urlparse(clean)
    if (
        parsed.scheme == "https"
        and parsed.netloc in {"open.spotify.com", "www.open.spotify.com"}
    ):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            return f"spotify:{parts[0]}:{parts[1]}"

    raise ValueError(f"Unsupported Spotify resource: {value}")


def _load_config(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        raise FileNotFoundError(f"Spotify config not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    client_id = str(config.get("client_id", "")).strip()
    redirect_uri = str(config.get("redirect_uri", "")).strip()
    if not client_id or not redirect_uri:
        raise ValueError("Spotify config requires client_id and redirect_uri.")

    return {"client_id": client_id, "redirect_uri": redirect_uri}


def _configure_browser_for_wsl() -> None:
    windows_browser = Path("/mnt/c/Windows/System32/rundll32.exe")
    if not windows_browser.exists():
        return

    browser = webbrowser.GenericBrowser(
        [str(windows_browser), "url.dll,FileProtocolHandler", "%s"]
    )
    webbrowser.register(
        "windows-default",
        None,
        browser,
        preferred=True,
    )


class SpotifyController:
    """Own the five deterministic Spotify operations exposed through GHOST."""

    SCOPES = " ".join(
        [
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-modify-playback-state",
            "playlist-read-private",
        ]
    )

    def __init__(
        self,
        config_path: Path | None = None,
        token_path: Path | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self._cached_device: dict[str, Any] | None = None
        self._keepalive_stop: threading.Event | None = None
        self._keepalive_thread: threading.Thread | None = None
        self._settings_timer: threading.Timer | None = None

        if client is not None:
            self._client = client
            return

        repo_root = Path(__file__).resolve().parents[3]
        resolved_config = (
            config_path or repo_root / "data/tools/spotify/config.json"
        )
        resolved_token = (
            token_path or repo_root / "data/tools/spotify/auth/token.json"
        )
        config = _load_config(resolved_config)
        resolved_token.parent.mkdir(parents=True, exist_ok=True)
        _configure_browser_for_wsl()

        auth = SpotifyPKCE(
            client_id=config["client_id"],
            redirect_uri=config["redirect_uri"],
            scope=self.SCOPES,
            cache_path=str(resolved_token),
            open_browser=True,
        )
        self._client = spotipy.Spotify(auth_manager=auth)

    def device_ready(self) -> dict[str, Any]:
        """Return current usable Spotify Connect device readiness."""
        device = self._require_ready_device()
        return {
            "ready": True,
            "device": {
                "name": device["name"],
                "type": device["type"],
                "is_active": device["is_active"],
            },
        }

    def playlist_tracks(self, parent_uri: str) -> dict[str, Any]:
        """Return one Spotify playlist in exact stored order."""
        device = self._device(refresh=True)
        result: dict[str, Any] = {
            "ready": True,
            "device": {
                "name": device["name"],
                "type": device["type"],
            },
        }
        canonical_parent = normalize_spotify_resource(parent_uri)
        if canonical_parent.split(":", 2)[1] != "playlist":
            raise ValueError("parent_uri must be a Spotify playlist URI")

        playlist_id = canonical_parent.rsplit(":", 1)[1]
        tracks: list[dict[str, Any]] = []
        offset = 0

        while True:
            page = self._client.playlist_items(
                playlist_id,
                limit=50,
                offset=offset,
            )
            entries = page.get("items") or []
            for index, entry in enumerate(entries):
                item = (entry or {}).get("item")
                if item is None:
                    item = (entry or {}).get("track")

                position = offset + index + 1
                if not item:
                    tracks.append(
                        {
                            "position": position,
                            "title": None,
                            "artists": [],
                            "uri": None,
                            "type": None,
                            "available": False,
                        }
                    )
                    continue

                artists = [
                    str(artist.get("name"))
                    for artist in (item.get("artists") or [])
                    if artist.get("name")
                ]
                tracks.append(
                    {
                        "position": position,
                        "title": item.get("name"),
                        "artists": artists,
                        "uri": item.get("uri"),
                        "type": item.get("type"),
                        "available": bool(item.get("uri")),
                    }
                )

            total = int(page.get("total") or len(tracks))
            offset += len(entries)
            if not entries or not page.get("next") or offset >= total:
                break

        result.update(
            {
                "parent_uri": canonical_parent,
                "track_count": len(tracks),
                "tracks": tracks,
            }
        )
        return result

    def start(
        self,
        parent_uri: str,
        starter_track_uri: str,
    ) -> dict[str, Any]:
        """Start audible playback first; schedule secondary settings afterward."""
        self._cancel_keepalive()
        self._cancel_settings()

        canonical_parent = normalize_spotify_resource(parent_uri)
        parent_type = canonical_parent.split(":", 2)[1]
        if parent_type not in {"playlist", "album"}:
            raise ValueError("parent_uri must be a Spotify playlist or album URI")

        canonical_item = normalize_spotify_resource(starter_track_uri)
        if canonical_item.split(":", 2)[1] not in {"track", "episode"}:
            raise ValueError(
                "starter_track_uri must be a Spotify track or episode URI"
            )

        device = self._require_ready_device()
        device_id = str(device["id"])

        try:
            self._client.start_playback(
                device_id=device_id,
                context_uri=canonical_parent,
                offset={"uri": canonical_item},
                position_ms=0,
            )
        except SpotifyException as error:
            if error.http_status != 404:
                raise
            device = self._device(refresh=True)
            device_id = str(device["id"])
            self._client.start_playback(
                device_id=device_id,
                context_uri=canonical_parent,
                offset={"uri": canonical_item},
                position_ms=0,
            )

        self._schedule_settings(device_id)
        return {
            "action": "started",
            "parent_uri": canonical_parent,
            "starter_track_uri": canonical_item,
            "device": device["name"],
            "settings_scheduled": True,
            "settings_delay_seconds": PLAYBACK_SETTINGS_DELAY_SECONDS,
        }

    def add_queue(self, track_uris: list[str]) -> dict[str, Any]:
        """Add exact track URIs to Spotify's live queue in supplied order."""
        if not track_uris:
            raise ValueError("track_uris must contain at least one track URI")

        canonical_tracks: list[str] = []
        for value in track_uris:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("every track_uris item must be a non-empty string")
            canonical = normalize_spotify_resource(value)
            if canonical.split(":", 2)[1] != "track":
                raise ValueError("every track_uris item must be a Spotify track URI")
            canonical_tracks.append(canonical)

        device = self._require_ready_device()
        device_id = str(device["id"])
        queued_tracks: list[str] = []
        for index, track_uri in enumerate(canonical_tracks):
            try:
                self._client.add_to_queue(track_uri, device_id=device_id)
            except Exception as error:
                raise SpotifyQueuePartialFailure(
                    "Spotify queue insertion stopped before completion",
                    queued_track_uris=queued_tracks,
                    failed_track_uri=track_uri,
                    remaining_track_uris=canonical_tracks[index + 1 :],
                    delivery_uncertain=not isinstance(error, SpotifyException),
                ) from error
            queued_tracks.append(track_uri)

        return {
            "action": "queued",
            "track_count": len(canonical_tracks),
            "track_uris": canonical_tracks,
            "device": device["name"],
        }

    def pause(self) -> dict[str, Any]:
        """Pause immediately and then keep the cached Connect target alive."""
        self._cancel_settings()
        self._cancel_keepalive()

        device = self._device(refresh=True)
        device_id = str(device["id"])

        try:
            self._client.pause_playback(device_id=device_id)
        except SpotifyException as error:
            if error.http_status != 404:
                raise
            device = self._device(refresh=True)
            device_id = str(device["id"])
            self._client.pause_playback(device_id=device_id)

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._keepalive_loop,
            args=(device_id, stop_event),
            name="ghost-spotify-keepalive",
            daemon=True,
        )
        self._keepalive_stop = stop_event
        self._keepalive_thread = thread
        thread.start()

        return {
            "action": "paused",
            "device": device["name"],
            "keepalive": True,
            "keepalive_interval_seconds": KEEPALIVE_INTERVAL_SECONDS,
            "keepalive_max_seconds": KEEPALIVE_MAX_SECONDS,
        }

    def stop(self) -> dict[str, Any]:
        """Cancel background activity and pause the cached device immediately."""
        self._cancel_settings()
        self._cancel_keepalive()

        device = self._device(refresh=True)
        device_id = str(device["id"])

        try:
            self._client.pause_playback(device_id=device_id)
        except SpotifyException as error:
            if error.http_status != 404:
                raise
            device = self._device(refresh=True)
            device_id = str(device["id"])
            self._client.pause_playback(device_id=device_id)

        return {
            "action": "stopped",
            "device": device["name"],
            "keepalive": False,
        }

    def _require_ready_device(self) -> dict[str, Any]:
        """Refresh and require one usable Spotify Connect device."""
        return self._device(refresh=True)

    def _device(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._cached_device is not None and not refresh:
            return self._cached_device

        devices = self._client.devices().get("devices", [])
        usable: list[dict[str, Any]] = []
        for item in devices:
            device_id = str(item.get("id") or "").strip()
            if not device_id or bool(item.get("is_restricted")):
                continue
            usable.append(
                {
                    "id": device_id,
                    "name": str(item.get("name") or "Spotify device"),
                    "type": str(item.get("type") or ""),
                    "is_active": bool(item.get("is_active")),
                }
            )

        if not usable:
            self._cached_device = None
            raise SpotifyDeviceUnavailable(
                "No usable Spotify Connect device is available. "
                "Activate Spotify on the phone and press Play once, then retry."
            )

        usable.sort(
            key=lambda item: (
                not item["is_active"],
                item["type"].casefold() != "smartphone",
                item["name"].casefold(),
                item["id"],
            )
        )
        self._cached_device = usable[0]
        return self._cached_device

    def _schedule_settings(self, device_id: str) -> None:
        timer = threading.Timer(
            PLAYBACK_SETTINGS_DELAY_SECONDS,
            self._apply_settings,
            args=(device_id,),
        )
        timer.daemon = True
        self._settings_timer = timer
        timer.start()

    def _apply_settings(self, device_id: str) -> None:
        self._settings_timer = None
        try:
            self._client.shuffle(False, device_id=device_id)
        except Exception:
            pass
        try:
            self._client.repeat("off", device_id=device_id)
        except Exception:
            pass

    def _cancel_settings(self) -> None:
        timer = self._settings_timer
        self._settings_timer = None
        if timer is not None:
            timer.cancel()

    def _cancel_keepalive(self) -> None:
        stop_event = self._keepalive_stop
        self._keepalive_stop = None
        self._keepalive_thread = None
        if stop_event is not None:
            stop_event.set()

    def _keepalive_loop(
        self,
        device_id: str,
        stop_event: threading.Event,
    ) -> None:
        deadline = time.monotonic() + KEEPALIVE_MAX_SECONDS

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return

            wait_seconds = min(KEEPALIVE_INTERVAL_SECONDS, remaining)
            if stop_event.wait(wait_seconds):
                return
            if time.monotonic() >= deadline:
                return

            try:
                self._client.transfer_playback(
                    device_id,
                    force_play=False,
                )
            except Exception:
                continue
