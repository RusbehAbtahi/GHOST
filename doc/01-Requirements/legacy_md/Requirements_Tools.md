# Requirements_Tools.md

## 1. Purpose and scope

The GHOST Tools subsystem owns deterministic integrations with external services. A Tool performs concrete service operations; it does not own user memory, semantic retrieval, prompt interpretation, or reusable Skill instructions.

The first Tool is Spotify.

## 2. Filesystem ownership

Production tool code lives under:

`ragstream/tools/<tool_name>/`

Persistent local runtime data for a tool lives under:

`data/tools/<tool_name>/`

Tool runtime data must not be treated as source code or as user knowledge memory. Credentials, tokens, and environment-specific state must not be committed to Git.

## 3. Spotify Tool

The Spotify Tool shall provide deterministic Spotify Web API operations through a small Python controller and CLI adapter.

The controller shall use Spotify user authorization through Authorization Code with PKCE and shall not require a Spotify Client Secret for the local laptop implementation.

The local Spotify configuration shall contain the Spotify Client ID and redirect URI. OAuth token state shall be stored separately under `data/tools/spotify/auth/`.

The Spotify Tool shall support these user-account operations:

- authorize and refresh OAuth access;
- list available Spotify Connect devices;
- inspect current playback;
- start playback from Spotify track, episode, album, artist, or playlist references supported by the API;
- start an ordered sequence of track or episode references;
- append track or episode references to the Spotify queue;
- pause, resume, next, and previous controls;
- direct playback/control to an explicitly named Spotify Connect device when requested.

Spotify URLs accepted by the CLI shall be normalized into Spotify URIs before API execution.

## 4. CLI boundary

`spotify_cli.py` shall remain a thin command-line adapter. It may parse arguments, call the Spotify controller, and render results, but Spotify API behavior shall remain owned by `spotify_controller.py`.

The initial CLI commands are:

- `auth`
- `devices`
- `status`
- `play`
- `queue`
- `pause`
- `resume`
- `next`
- `previous`

## 5. Memory and Skill separation

The Spotify Tool shall not own the user's music collection. Personal music knowledge, preferred recordings, performer/work descriptions, and stored Spotify links belong to ordinary GHOST Memory/RAGMEM collections.

Reusable instructions that teach GHOST how to retrieve a user's requested music and translate that retrieval into Spotify CLI actions belong to GHOST Skills, not to the Spotify Tool implementation.

Therefore the responsibility split is:

- Memory/RAGMEM: what belongs to the user's music collection;
- Skill: how GHOST interprets a music request and combines retrieval with Tool commands;
- Spotify Tool: deterministic execution against Spotify.

## 6. Local and AWS runtime separation

The same Spotify Python code may later run on the local laptop and AWS, but authorization and runtime state are environment-specific. A working local authorization shall not imply a working AWS authorization.

Local and AWS Spotify token/configuration state shall remain independent unless a future requirement explicitly changes that policy.
