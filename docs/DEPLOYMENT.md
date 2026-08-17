# Deployment

Avant Atlas runs in two places, on purpose.

| | Where | What it does |
|---|---|---|
| **Data plane** | this Mac, under `launchd` | Owns the corpus. Runs the weekly freshness sweep (link health → source re-crawl → rebuild → commit → redeploy). Serves a local copy on `127.0.0.1:8420`. |
| **Web plane** | miren app `avant-atlas` | Serves the public site at **<https://atlas.freeq.at>**. Stateless: it is a container that builds the site from `data/*.yaml` and serves it. |

The split matters. The corpus is a git repository of human-editable YAML that
accumulates history, so it wants to live on a machine with a shell and a
long memory. The website is a pile of generated files, so it wants to live
wherever it can be reached cheaply and never go down. Nothing important is
stored in the container; a redeploy is disposable by design.

## The public deployment

```bash
miren deploy -f          # build + roll out
miren logs -f            # tail
miren app status         # version, env, routes
miren rollback           # previous version
```

`[build] onbuild` runs `python -m atlas.cli build` *inside* the container, so
the generated HTML is never committed and the deployed site is guaranteed to
match the deployed data.

### Request path

```
client → nginx :443 (TLS, on the cluster host)
       → miren router 127.0.0.1:8090   (dispatches on Host header)
       → avant-atlas web sandbox :8000 (uvicorn)
```

The nginx server block lives at `/etc/nginx/sites-available/atlas.freeq.at` on
the cluster host and lists all hostnames the app answers to. TLS is Certbot:

```bash
certbot --nginx -d atlas.freeq.at --redirect
```

### About `atlas.run.garden`

That is the intended home, and everything on our side is already wired for it:

- the miren route exists (`miren route set atlas.run.garden avant-atlas`)
- the nginx server block on the cluster host lists `atlas.run.garden`
- requests with `Host: atlas.run.garden` already serve correctly:
  `curl -H 'Host: atlas.run.garden' http://<cluster-ip>/healthz` → `200`

What is missing is a **public DNS A record**, and `run.garden` is Miren, Inc's
zone — our DNSimple credentials do not control it, and a self-hosted cluster's
`route set` does not create records in it. `atlas.run.garden` is `NXDOMAIN`
today.

To finish the switch once that record points at the cluster:

```bash
# 1. canonical origin
sed -i '' 's|https://atlas.freeq.at|https://atlas.run.garden|' .miren/app.toml
# 2. certificate
ssh root@<cluster-host> 'certbot --nginx -d atlas.run.garden --redirect'
# 3. ship
miren deploy -f
```

Order matters: `ATLAS_BASE_URL` is baked into every `<link rel="canonical">`,
Open Graph URL and sitemap entry, so pointing it at a name that does not resolve
would get the site dropped from search results — the opposite of the reason the
multi-page site exists.

## The local services

```bash
cp deploy/com.avantatlas.*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.avantatlas.web.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.avantatlas.refresh.plist
```

- `com.avantatlas.web` — uvicorn on `127.0.0.1:8420`, `KeepAlive`, logs to
  `/tmp/avant-atlas-web.log`.
- `com.avantatlas.refresh` — `scripts/refresh.sh --deploy`, Mondays 06:15, logs
  to `/tmp/avant-atlas-refresh.log`.

Run the sweep now instead of waiting for Monday:

```bash
launchctl kickstart -p gui/$(id -u)/com.avantatlas.refresh
tail -f /tmp/avant-atlas-refresh.log
```

The sweep only redeploys when data actually changed, so a quiet week costs
nothing. It never edits a score: a moved page or a dead link sets
`needs_human_review`, which surfaces the venue in `atlas verify` and prints a
warning box on its public page.

## If you want the public traffic to hit *this* Mac

Miren cannot proxy to an upstream it does not run, and `miren server` installs
on Linux (or Docker, which is not installed here) — so a miren route cannot
point at this machine. Two honest options if that is the requirement:

1. **Reverse tunnel.** Hold `ssh -N -R 127.0.0.1:8421:127.0.0.1:8420
   root@<cluster-host>` open from a launchd agent, and add an nginx server block
   that proxies a hostname to `127.0.0.1:8421`. Public traffic then really is
   served by this Mac. It bypasses miren's router and dies with the tunnel or
   the laptop, which is why it is not the default.
2. **Local miren cluster.** Install Docker, `miren server docker install`, and
   deploy to a cluster running here. Then this machine needs a stable public
   address and inbound 80/443 — a residential IP makes that fragile.

The current split gets the same practical result: the work happens on this
machine, and the site is reachable from anywhere.
