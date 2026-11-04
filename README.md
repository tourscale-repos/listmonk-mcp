# Listmonk MCP

Read + write Model Context Protocol server for the TourScale Listmonk instance at [listmonk.tourscale.com](https://listmonk.tourscale.com). Lets agents query lists/subscribers/campaigns/templates and send emails (transactional or campaign-based).

## What it exposes

**Read:**
- `health` — connectivity + auth probe
- `list_lists`, `get_list`
- `list_subscribers(list_id, query, page)`, `get_subscriber`, `find_subscriber_by_email`
- `list_templates`, `get_template`
- `list_campaigns(status)`, `get_campaign`
- `dashboard_stats`

**Write:**
- `add_subscriber(email, name, list_ids, attribs_json)` — single create
- `update_subscriber(id, payload_json)`
- `add_subscribers_to_lists(subscriber_ids, list_ids, action)` — bulk attach/remove/unsubscribe
- `create_campaign(name, subject, list_ids, body, template_id, ...)`
- `start_campaign(id)` / `cancel_campaign(id)`
- `tx_send(subscriber_email, template_id, data_json)` — transactional one-off

## How auth works

`Authorization: token <user>:<token>` — Listmonk's API user scheme. The `claude-api` user is type=api, with the token stored **plaintext** in `users.password` (Listmonk v6 quirk: API user tokens are NOT bcrypt-hashed despite the column name; bcrypt-hashed values fail auth even at the correct format).

To rotate: pick a new random token, run `UPDATE users SET password='<new_token>' WHERE username='claude-api'` against `ts-listmonk-db`, restart `ts-listmonk` (so user cache flushes), update `LISTMONK_API_TOKEN` in master env + container `.env`, recreate `ts-listmonk-mcp`.

## Deployment

Deploys from GitHub: the server pulls `main` and builds there, per the
[deployment policy](https://github.com/tourscale-repos/tourscale-engineering-policies/blob/main/deployment.md).
Never copy code to the server or build images on your machine. The server has no
checkout of this repo yet, so there is no approved deploy command until one is set up
(policy: *Setting up a new Hetzner app*).

It runs as a service inside the shared `/opt/tourscale` stack. Once the checkout
exists (`<checkout>` below) and the service builds from it, a deploy pulls it and
rebuilds only this service:

```sh
ssh -t hetzner 'sudo -i sh -c "git -C <checkout> pull --ff-only && cd /opt/tourscale && docker compose -p tourscale -f docker-compose.services.yml up -d --build --no-deps ts-listmonk-mcp"'
```

- Container: `ts-listmonk-mcp` on `tourscale-net`
- Port: `127.0.0.1:8097` (loopback only)
- Compose entry: `/opt/tourscale/docker-compose.services.yml`, service `ts-listmonk-mcp`, Compose project `tourscale`
- Env file: `/opt/tourscale/listmonk-mcp/.env` (sourced from master env)

## Local dev

```bash
LISTMONK_URL=https://listmonk.tourscale.com \
LISTMONK_API_USER=claude-api \
LISTMONK_API_TOKEN=... \
MCP_TRANSPORT=http \
python3 server.py
```
