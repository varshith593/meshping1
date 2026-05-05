# meshtop

`meshtop` is a Python CLI that measures latency across multiple network nodes and renders a live terminal matrix. It supports:

- Agentless TCP connect probing for "one node measures many targets"
- UDP agent probing for distributed mesh measurements
- A Rich live matrix with a network health score, human labels, stats, alerts, heatmap, and local system panel
- Split-brain diagnosis that compares your gateway and the public internet and tells you whether to blame Wi-Fi or your ISP
- Hidden IPv4 vs IPv6 protocol race checks that flag slow IPv6 / Happy Eyeballs problems
- Contextual usage profiles for `work`, `gaming`, and `video`
- Auto-naming for common local services and best-effort reverse DNS naming for IP targets
- Topology clustering and asymmetric path detection
- Service fingerprinting from live TCP banners
- Opt-in SQLite logging with in-memory session history by default, plus `.mpr` replay recording
- Local machine health checks, loopback baseline, NIC counters, CPU/RAM correlation, and `doctor`
- Natural language quick-starts, sandbox targets, diff mode, clipboard sharing, and mute/snooze controls
- Agent auto-discovery on a subnet with `meshtop discover`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

Launch the default sandbox view with no arguments:

```bash
meshtop
```

This opens a live TUI against Cloudflare, Google, and your local router so a first-time user sees a healthy baseline immediately.

Probe a single TCP target:

```bash
meshtop probe github=github.com:443
```

Probe multiple targets once:

```bash
meshtop probe github=github.com:443 openai=api.openai.com:443 cloudflare=cloudflare.com:443
```

Run the live agentless matrix:

```bash
meshtop mesh --nodes github=github.com:443,openai=api.openai.com:443,cloudflare=cloudflare.com:443
```

Run with opt-in logging and record a replay file:

```bash
meshtop mesh web=localhost:8080 db=localhost:5432 \
  --log ~/.meshtop/history.db \
  --record incident.mpr
```

Run the local resource correlation view:

```bash
meshtop top web=localhost:8080 db=localhost:5432
```

Use a profile tuned for the task:

```bash
meshtop mesh --profile gaming --nodes cloudflare=1.1.1.1:443,google=8.8.8.8:443
meshtop top --profile video
```

Run the built-in 8-service localhost demo:

```bash
meshtop demo
```

Start an agent:

```bash
meshtop agent --name web1 --host 0.0.0.0 --port 7777 \
  --peers web2=10.0.0.12:7777,db1=10.0.0.13:7777 \
  --coordinator 10.0.0.10:7778
```

Discover agents on a subnet:

```bash
meshtop discover --subnet 192.168.1.0/24
```

Run a distributed coordinator:

```bash
meshtop mesh --distributed \
  --agents web1=10.0.0.11:7777,web2=10.0.0.12:7777,db1=10.0.0.13:7777 \
  --listen 0.0.0.0:7778
```

Compare two paths:

```bash
meshtop diff cloudflare=1.1.1.1:443 google=8.8.8.8:443
```

Run a non-interactive health check:

```bash
meshtop check --nodes db1:5432,redis1:6379 --max-p99 5 --max-loss 1
```

Diagnose the local network stack:

```bash
meshtop doctor --ports 80,443,22,5432,9092,6379
```

`doctor` checks loopback, default gateway, DNS, internet reachability, IPv6, MTU probing, local TCP/NIC counters, and outbound ports.

Replay a captured session:

```bash
meshtop replay incident.mpr --speed 2x
```

Natural language shortcut:

```bash
meshtop "check my dns and the router"
```

## Keyboard Controls

- `q`: quit live view
- `s`: toggle stats panel
- `a`: toggle alerts panel
- `c`: toggle cluster view
- `h`: toggle heatmap view
- `l`: toggle local machine health
- `S`: copy a human-readable support summary to the clipboard
- `p`: cycle `work` / `gaming` / `video` scoring
- `M`: mute or unmute the selected target
- `1` / `2` / `3`: set refresh rate
- `r`: cycle refresh rate
- `j` / Down Arrow: scroll down
- `k` / Up Arrow: scroll up
- `?`: show key bindings

## Notes

- TCP probing uses connect-time latency and distinguishes timeouts from connection refusal.
- TCP probing automatically uses `HTTPS_PROXY`, `HTTP_PROXY`, or `ALL_PROXY` when those variables are set. Use `--no-proxy` to force direct sockets.
- UDP agent mode uses a fixed 20-byte request and 28-byte echo reply for latency measurements.
- Use `meshtop discover --subnet ...` when you want to find running agents on a LAN.
- Heatmap history lives in memory during a normal session; use `--log` if you want a SQLite file.
- Replay files use a compact binary `.mpr` format that stores node metadata and probe records.
- For full mesh mode, start agents on each node and point them at the coordinator. You can also provide agent lists through `meshtop_AGENTS`.

## Full Guide

See [docs/GUIDE.md](docs/GUIDE.md) for the feature review, architecture, command examples, alert rules, and operating workflow.
See [docs/SRS.md](docs/SRS.md) for the software requirements specification.
