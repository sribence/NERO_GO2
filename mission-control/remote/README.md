# remote (Tailscale integration -- no HTTP port of its own)

Docker-only Tailscale integration so the Jetson (and mission-control's
other services) become reachable over the same tailnet already used by
`localai`/`main`, **without touching the native Jetson OS networking**.
That's a hard safety rule for this project: the native system is never
modified, everything new here is Docker-only, userspace-networking,
non-privileged.

This pillar has two independent pieces:

1. `docker-compose.fragment.yml` -- a `tailscale` service definition to be
   merged into the top-level `docker-compose.yml`.
2. `log_shipper.py` -- a small script that periodically ships a blackbox
   summary to a remote endpoint (or just logs locally if none is set).

**Nothing here auto-connects to any tailnet.** Actually connecting
requires your own Tailscale account and an auth key -- this scaffold
prepares the plumbing but does not (and must not) run on its own without
you supplying `TS_AUTHKEY`.

## 1. Generating a Tailscale auth key

1. Go to the Tailscale admin console -> **Settings -> Keys** ->
   **Generate auth key**.
2. Choose:
   - **Reusable**: on, if you want to be able to recreate this container
     (e.g. after `docker compose down -v`, which wipes the named volume
     and thus the saved identity) without generating a new key each time.
     Off if you'd rather mint a fresh key per deploy.
   - **Ephemeral**: generally **off** for this use case. Ephemeral nodes
     are removed from the tailnet as soon as they disconnect, which is
     right for short-lived CI runners but wrong here -- you want the
     mission-control node to keep a stable tailnet identity/IP between
     robot reboots and container restarts, which is exactly what
     `TS_STATE_DIR` on a named volume is for.
   - **Tags**: pre-authorize the key with the tag used in the fragment
     (`tag:go2-mission-control`, or whatever your tailnet's ACL policy
     defines) so the node doesn't need manual approval in the admin
     console every time.
   - **Expiry**: keys expire (default 90 days). A reusable key surviving
     past expiry still won't let a *new* node join -- only nodes already
     authenticated with it keep working. Plan to rotate.
3. Copy the generated key (`tskey-auth-...`). Treat it like a password --
   it grants a new device access to your tailnet.

## 2. Setting `TS_AUTHKEY`

Never hardcode it in `docker-compose.fragment.yml` or anywhere in this
repo. Two options:

```bash
# option A: shell env var before `docker compose up`
export TS_AUTHKEY=<IDE-JON-A-SAJAT-KULCSOD>

# option B: a .env file next to docker-compose.yml (make sure it's
# gitignored -- check the repo's top-level .gitignore before relying on
# this)
echo "TS_AUTHKEY=<IDE-JON-A-SAJAT-KULCSOD>" >> .env
```

With `TS_AUTHKEY` unset, the fragment's `${TS_AUTHKEY:-}` resolves to an
empty string -- the `tailscale` container starts but sits idle, logging
that it needs an auth key. It will not join any tailnet.

## 3. Merging the fragment

This fragment is deliberately **not** auto-merged -- copy the `services:`
and `volumes:` blocks from `docker-compose.fragment.yml` into the
top-level `mission-control/docker-compose.yml` by hand (or have whoever
owns that file do it), so the person merging can see exactly what's being
added to their compose file and decide how to attach other pillars to it.

## Exposing a service over the tailnet once merged

Two ways to make e.g. `blackbox` (port 9108) reachable from your other
tailnet machines:

**(a) Share the tailscale container's network namespace** -- simplest,
recommended for a small number of services:

```yaml
services:
  blackbox:
    # ... existing blackbox service definition ...
    network_mode: "service:tailscale"
    depends_on:
      - tailscale
    # do NOT also set `ports:` here -- with network_mode: service:X the
    # container has no network of its own to publish ports from
```

Now `blackbox` is reachable at `http://mission-control:9108/...` from any
other machine on the tailnet (using the `hostname: mission-control` set in
the fragment), with zero change to blackbox's own code.

**(b) Tailscale Serve/Funnel inside the tailscale container** -- if you
want a single tailnet hostname fronting multiple pillars on different
paths, or want to control what's exposed more granularly, run
`tailscale serve` (tailnet-only) or `tailscale funnel` (public internet --
almost certainly NOT what you want for a robot control API) from inside
the tailscale container, proxying to each pillar by its bridge-network
service name and port. This needs the container's `TS_EXTRA_ARGS` or an
exec'd command to configure the serve rules; not set up by default in the
fragment since it wasn't asked for -- (a) is enough for "reachable from my
other tailnet machines."

## 4. `log_shipper.py`

Run standalone (needs `requests`, no `core/` dependency -- it talks to
`blackbox` over HTTP, not to the robot):

```bash
cd mission-control/remote
pip install -r requirements.txt
BLACKBOX_URL=http://localhost:9108 SHIP_INTERVAL_SECONDS=30 python log_shipper.py
```

Every `SHIP_INTERVAL_SECONDS` (default 300) it polls blackbox's
`GET /buffer/status` and `GET /incidents`, builds a compact summary
(buffer stats + any incidents created since the last ship), and:

- POSTs it as JSON to `REMOTE_LOG_ENDPOINT` if that env var is set, or
- otherwise logs locally (`logs/events.jsonl` + stdout) exactly what it
  *would* have POSTed -- so the whole pipeline is visible and testable
  without any real remote server configured yet.

| Var | Default | Meaning |
|---|---|---|
| `BLACKBOX_URL` | `http://blackbox:9108` | blackbox service base URL (service name inside compose; `http://localhost:9108` for a standalone run) |
| `REMOTE_LOG_ENDPOINT` | *(unset)* | Where to POST summaries; unset = log-only mode |
| `SHIP_INTERVAL_SECONDS` | `300` | Poll/ship interval |
| `HTTP_TIMEOUT_SECONDS` | `10` | Timeout for both the blackbox poll and the remote POST |

In Docker, `log_shipper` should run on the same network as `blackbox`
(the default compose bridge network is fine -- it doesn't need to be on
the tailscale network namespace itself unless `REMOTE_LOG_ENDPOINT` is
only reachable *through* the tailnet, in which case give it
`network_mode: "service:tailscale"` too, same as option (a) above).

## Known limitations

- The fragment doesn't attempt to auto-detect or reconcile an existing
  tailnet device with the same name -- if you tear down and recreate the
  named volume (`docker compose down -v`), you get a *new* tailnet
  identity and the old one will show as offline in the admin console until
  you manually remove it.
- `log_shipper.py` ships a summary, not raw incident data (no log lines,
  no frames) -- by design, to keep payloads small over what may be a
  metered/slow link. If full incident detail needs to reach a remote
  server, extend it to pull `GET /incidents/{id}` for the specific
  incidents in `recent_incidents` and ship those too.
- No retry/backoff beyond "try again next interval" -- a single failed
  ship is just logged and the next cycle tries again; nothing is queued or
  retried mid-interval.
