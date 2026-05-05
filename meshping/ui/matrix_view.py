from __future__ import annotations

import asyncio
import contextlib
import os
import queue
from pathlib import Path
import select
import shutil
import sys
import termios
import threading
import tty
from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from meshping.load.stats import sparkline
from meshping.local.clipboard import copy_text
from meshping.local.nic import NICWatcher, default_interface
from meshping.mesh.coordinator import Coordinator
from meshping.ui.alert_view import render_alerts_table
from meshping.ui.cluster_view import render_cluster_table, render_topology_diagram
from meshping.ui.heatmap_view import render_heatmap_table
from meshping.ui.histogram_view import render_histogram
from meshping.ui.insights import (
    cell_summary,
    health_score,
    health_score_text,
    next_profile,
    status_label,
    status_style,
    support_summary,
)
from meshping.ui.local_panel import render_local_health_table
from meshping.ui.stats_view import render_stats_table
from meshping.ui.time_series_view import render_time_series

WELCOME_FILE = Path.home() / ".meshping" / "welcome_seen"
EXPORT_DIR = Path.home() / ".meshping"


class MeshDashboard:
    def __init__(
        self,
        *,
        console: Console | None = None,
        show_local: bool = False,
    ) -> None:
        self.console = console or Console()
        self.show_stats = True
        self.show_alerts = True
        self.show_clusters = False
        self.show_local = show_local
        self.show_heatmap = False
        self.show_help = False
        self.show_time_series = False
        self.show_histogram = False
        self.cluster_topology = False
        self.show_welcome = not WELCOME_FILE.exists()
        self.scroll_offset = 0
        self.selected_source_index = 0
        self.selected_target_index = 0
        self.refresh_options = [1.0, 2.0, 5.0]
        self.quit_requested = False
        self.export_notice: str | None = None
        self.nic_watcher: NICWatcher | None = None
        self.muted_targets: set[str] = set()
        self._keys: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stop_reader = threading.Event()
        self._reader_thread: threading.Thread | None = None

    async def run(self, coordinator: Coordinator) -> None:
        self._start_keyboard_reader()
        try:
            with Live(self.render(coordinator), console=self.console, refresh_per_second=8) as live:
                while not self.quit_requested and not coordinator.stop_event.is_set():
                    self._handle_keys(coordinator)
                    live.update(self.render(coordinator))
                    await asyncio.sleep(coordinator.settings.refresh_rate_s)
        finally:
            self._stop_keyboard_reader()
            coordinator.stop()

    def render(self, coordinator: Coordinator) -> Group:
        self._ensure_nic_watcher(coordinator)
        if self.show_welcome:
            parts = [Panel(self._render_welcome(coordinator), title="Welcome")]
        else:
            parts = []
        parts.append(Panel(self._render_matrix(coordinator), title="Latency Matrix"))
        if self.show_stats:
            parts.append(Panel(render_stats_table(coordinator), title="Stats"))
        if self.show_alerts:
            parts.append(
                Panel(
                    render_alerts_table(coordinator, muted_targets=self.muted_targets),
                    title="Alerts",
                )
            )
        if self.show_clusters:
            cluster_view = (
                render_topology_diagram(
                    coordinator.clusters,
                    inter_cluster_latency=self._inter_cluster_latency(coordinator),
                )
                if self.cluster_topology
                else render_cluster_table(coordinator.clusters)
            )
            parts.append(Panel(cluster_view, title="Clusters"))
        if self.show_local:
            parts.append(
                Panel(
                    render_local_health_table(
                        nic_watcher=self.nic_watcher,
                        split_brain=coordinator.split_brain,
                    ),
                    title="Local",
                )
            )
        if self.show_heatmap:
            source_id, target_id = self._selected_pair(coordinator)
            parts.append(
                Panel(
                    render_heatmap_table(
                        coordinator.heatmap_rows(source_id, target_id),
                        title=f"Heatmap {source_id} -> {target_id}",
                    ),
                    title="Heatmap",
                )
            )
        selected_cell = self._selected_cell(coordinator)
        if self.show_time_series and selected_cell:
            parts.append(
                Panel(
                    render_time_series(selected_cell),
                    title="Time Series",
                )
            )
        if self.show_histogram and selected_cell:
            parts.append(Panel(render_histogram(selected_cell), title="Histogram"))
        if self.show_help:
            parts.append(Panel(self._render_help(), title="Keys"))
        if self.export_notice:
            parts.append(Panel(Text(self.export_notice, style="yellow"), title="Export"))
        parts.append(Panel(self._render_status_bar(coordinator), title="Status"))
        return Group(*parts)

    def _render_matrix(self, coordinator: Coordinator) -> Table:
        table = Table(expand=True)
        node_map = coordinator.node_map()
        profile = coordinator.settings.usage_profile
        targets = coordinator.target_order()
        sources = coordinator.source_order()
        self._clamp_selection(sources, targets)
        max_rows = max(shutil.get_terminal_size((120, 40)).lines - 18, 5)
        self.scroll_offset = min(self.scroll_offset, max(len(sources) - 1, 0))
        self.scroll_offset = min(
            self.scroll_offset,
            max(len(sources) - max_rows, 0),
        )
        if self.selected_source_index < self.scroll_offset:
            self.scroll_offset = self.selected_source_index
        if self.selected_source_index >= self.scroll_offset + max_rows:
            self.scroll_offset = self.selected_source_index - max_rows + 1
        visible_sources = sources[self.scroll_offset : self.scroll_offset + max_rows]
        selected_source_id = sources[self.selected_source_index] if sources else None
        selected_target_id = targets[self.selected_target_index] if targets else None

        table.add_column("Source")
        for target_id in targets:
            label = node_map.get(target_id).display_name if target_id in node_map else target_id
            if target_id == selected_target_id:
                label = f"[reverse]{label}[/reverse]"
            table.add_column(label, justify="right")

        for source_id in visible_sources:
            source_label = node_map.get(source_id).display_name if source_id in node_map else source_id
            if source_id == selected_source_id:
                source_label = f"[reverse]{source_label}[/reverse]"
            row = [source_label]
            for target_id in targets:
                if source_id == target_id:
                    text = "[dim]N/A[/dim]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = "[reverse dim]N/A[/reverse dim]"
                    row.append(text)
                    continue
                cell = coordinator.matrix.get(source_id, target_id)
                if not cell:
                    text = "[dim]-[/dim]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = "[reverse dim]-[/reverse dim]"
                    row.append(text)
                    continue
                if cell.last_error == "timeout":
                    text = "[bold red]TIMEOUT[/bold red]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = "[reverse bold red]TIMEOUT[/reverse bold red]"
                    row.append(text)
                    continue
                if cell.last_error == "connection_refused" and cell.p50 is None:
                    text = "[magenta]REFUSED[/magenta]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = "[reverse magenta]REFUSED[/reverse magenta]"
                    row.append(text)
                    continue
                if cell.last_error and cell.last_error.startswith("proxy_connect_http_"):
                    code = cell.last_error.rsplit("_", 1)[-1]
                    text = f"[yellow]PROXY {code}[/yellow]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = f"[reverse yellow]PROXY {code}[/reverse yellow]"
                    row.append(text)
                    continue
                if cell.last_error == "proxy_timeout":
                    text = "[bold red]PROXY TIMEOUT[/bold red]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = "[reverse bold red]PROXY TIMEOUT[/reverse bold red]"
                    row.append(text)
                    continue
                if cell.last_error and cell.p50 is None:
                    text = f"[yellow]{cell.last_error[:18].upper()}[/yellow]"
                    if source_id == selected_source_id and target_id == selected_target_id:
                        text = f"[reverse yellow]{cell.last_error[:18].upper()}[/reverse yellow]"
                    row.append(text)
                    continue
                value = f"{status_label(cell, profile)} {cell_summary(cell)}"
                history = [sample for sample in cell.samples if sample is not None]
                if history:
                    value = f"{value} {sparkline(history[-10:])}"
                if cell.asymmetric and cell.asymmetry_ratio is not None:
                    value = f"{value} [purple]↕{cell.asymmetry_ratio:.1f}x[/purple]"
                if cell.protocol_race_note and "slower" in cell.protocol_race_note:
                    value = f"{value} [cyan]{cell.protocol_race_note}[/cyan]"
                style = "purple" if cell.asymmetric else status_style(cell, profile)
                if self._is_muted(source_id, target_id):
                    style = "dim"
                    value = f"MUTED {cell_summary(cell)}"
                if source_id == selected_source_id and target_id == selected_target_id:
                    style = f"reverse {style}"
                row.append(f"[{style}]{value}[/{style}]")
            table.add_row(*row)
        return table

    def _render_status_bar(self, coordinator: Coordinator) -> Text:
        text = Text()
        text.append(datetime.now().strftime("%H:%M:%S"))
        text.append("  ")
        text.append_text(
            health_score_text(
                health_score(
                    list(coordinator.matrix.iter_cells()),
                    coordinator.settings.usage_profile,
                ),
                coordinator.settings.usage_profile,
            )
        )
        text.append(f"  nodes={len(coordinator.nodes)}")
        text.append(f"  probes={coordinator.total_probes_sent}")
        text.append(f"  refresh={coordinator.settings.refresh_rate_s:.1f}s")
        if coordinator.network_context.summary:
            text.append(f"  network={coordinator.network_context.summary}")
        if coordinator.split_brain and coordinator.split_brain.diagnosis != "Path healthy":
            text.append(f"  blame={coordinator.split_brain.diagnosis}")
        source_id, target_id = self._selected_pair(coordinator)
        text.append(f"  selected={source_id}->{target_id}")
        text.append(
            "  keys: q quit | s stats | a alerts | c clusters | h heatmap | "
            "l local | enter time-series | J histogram | T topology | "
            "S support | M mute | p profile | E export | 1/2/3 refresh | ? help"
        )
        return text

    def _render_help(self) -> Group:
        table = Table(expand=True, title="Controls")
        table.add_column("Key")
        table.add_column("Action")
        for key, action in [
            ("q", "quit"),
            ("c", "toggle cluster view"),
            ("a", "toggle alerts"),
            ("h", "toggle heatmap"),
            ("l", "toggle local machine health"),
            ("Enter", "toggle time-series"),
            ("J", "toggle histogram"),
            ("T", "toggle cluster topology"),
            ("S", "copy current support summary"),
            ("M", "mute or unmute selected target"),
            ("p", "cycle usage profile"),
            ("E", "export selected heatmap CSV"),
            ("s", "toggle stats"),
            ("1/2/3", "set refresh rate"),
            ("arrows", "select source/target"),
        ]:
            table.add_row(key, action)
        legend = Table(expand=True, title="Color Guide")
        legend.add_column("Color")
        legend.add_column("Meaning")
        legend.add_row("[green]Green[/green]", "Healthy and stable")
        legend.add_row("[yellow]Yellow[/yellow]", "Degraded or jittery")
        legend.add_row("[red]Red[/red]", "Loss, timeouts, or severe lag")
        legend.add_row("[dim]Dim[/dim]", "Muted target or no data yet")
        glossary = Text(
            "Latency is travel time. Jitter is how uneven that travel time is. "
            "Loss means packets never arrived, which usually points to Wi-Fi, VPN, or upstream issues.",
            style="dim",
        )
        return Group(table, legend, glossary)

    def _render_welcome(self, coordinator: Coordinator) -> Group:
        network = coordinator.network_context.summary or "network context unavailable"
        body = Text()
        body.append("Latency is how long a packet takes to arrive.\n")
        body.append("Jitter is variation between packets; high jitter feels like stutter in calls and games.\n")
        body.append("Loss means packets are disappearing; that usually points to Wi-Fi, VPN, or ISP trouble.\n\n")
        body.append(f"Detected network: {network}\n")
        body.append("Press any key to start. Use ? anytime for help.", style="bold")
        return Group(body)

    def _handle_keys(self, coordinator: Coordinator) -> None:
        while True:
            try:
                key = self._keys.get_nowait()
            except queue.Empty:
                break
            if self.show_welcome:
                self._dismiss_welcome()
            if key == "q":
                self.quit_requested = True
            elif key == "p":
                coordinator.settings.usage_profile = next_profile(
                    coordinator.settings.usage_profile
                )
                self.export_notice = f"Profile set to {coordinator.settings.usage_profile}"
            elif key == "s":
                self.show_stats = not self.show_stats
            elif key == "a":
                self.show_alerts = not self.show_alerts
            elif key == "c":
                self.show_clusters = not self.show_clusters
            elif key == "h":
                self.show_heatmap = not self.show_heatmap
            elif key == "ENTER":
                self.show_time_series = not self.show_time_series
            elif key == "J":
                self.show_histogram = not self.show_histogram
            elif key == "T":
                self.cluster_topology = not self.cluster_topology
            elif key == "S":
                self._share_snapshot(coordinator)
            elif key == "M":
                self._toggle_mute(coordinator)
            elif key == "E":
                self._export_heatmap(coordinator)
            elif key == "l":
                self.show_local = not self.show_local
            elif key == "?":
                self.show_help = not self.show_help
            elif key in {"1", "2", "3"}:
                coordinator.settings.refresh_rate_s = self.refresh_options[int(key) - 1]
            elif key == "r":
                current = coordinator.settings.refresh_rate_s
                try:
                    index = self.refresh_options.index(current)
                except ValueError:
                    index = 0
                coordinator.settings.refresh_rate_s = self.refresh_options[
                    (index + 1) % len(self.refresh_options)
                ]
            elif key in {"DOWN", "j"}:
                self.selected_source_index += 1
            elif key in {"UP", "k"}:
                self.selected_source_index = max(0, self.selected_source_index - 1)
            elif key == "LEFT":
                self.selected_target_index = max(0, self.selected_target_index - 1)
            elif key == "RIGHT":
                self.selected_target_index += 1

    def _start_keyboard_reader(self) -> None:
        if not sys.stdin.isatty():
            return
        self._reader_thread = threading.Thread(
            target=self._keyboard_loop,
            name="meshping-keyboard",
            daemon=True,
        )
        self._reader_thread.start()

    def _stop_keyboard_reader(self) -> None:
        self._stop_reader.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.2)

    def _keyboard_loop(self) -> None:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._stop_reader.is_set():
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue
                char = os.read(fd, 1).decode("utf-8", errors="ignore")
                if char == "\x1b":
                    seq = os.read(fd, 2).decode("utf-8", errors="ignore")
                    if seq == "[A":
                        self._keys.put("UP")
                    elif seq == "[B":
                        self._keys.put("DOWN")
                    elif seq == "[C":
                        self._keys.put("RIGHT")
                    elif seq == "[D":
                        self._keys.put("LEFT")
                    continue
                if char in {"\r", "\n"}:
                    self._keys.put("ENTER")
                    continue
                if char in {"q", "s", "a", "r", "j", "k", "c", "h", "l", "?", "1", "2", "3", "J", "T", "E", "S", "M", "p"}:
                    self._keys.put(char)
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _clamp_selection(self, sources: list[str], targets: list[str]) -> None:
        if not sources or not targets:
            self.selected_source_index = 0
            self.selected_target_index = 0
            return
        self.selected_source_index = min(self.selected_source_index, len(sources) - 1)
        self.selected_target_index = min(self.selected_target_index, len(targets) - 1)

    def _selected_pair(self, coordinator: Coordinator) -> tuple[str, str]:
        sources = coordinator.source_order()
        targets = coordinator.target_order()
        self._clamp_selection(sources, targets)
        source_id = sources[self.selected_source_index] if sources else "-"
        target_id = targets[self.selected_target_index] if targets else "-"
        return source_id, target_id

    def _selected_cell(self, coordinator: Coordinator):
        source_id, target_id = self._selected_pair(coordinator)
        if source_id == target_id:
            return None
        return coordinator.matrix.get(source_id, target_id)

    def _ensure_nic_watcher(self, coordinator: Coordinator) -> None:
        if self.nic_watcher:
            return
        interface = default_interface()
        if interface:
            self.nic_watcher = NICWatcher(interface=interface)

    def _inter_cluster_latency(self, coordinator: Coordinator) -> dict[tuple[str, str], float]:
        values: dict[tuple[str, str], float] = {}
        for left in coordinator.clusters:
            for right in coordinator.clusters:
                if left.id >= right.id:
                    continue
                best: float | None = None
                for left_node in left.node_ids:
                    for right_node in right.node_ids:
                        cell = coordinator.matrix.get(left_node, right_node)
                        if cell and cell.p50 is not None:
                            best = cell.p50 if best is None else min(best, cell.p50)
                if best is not None:
                    values[(left.id, right.id)] = best
        return values

    def _export_heatmap(self, coordinator: Coordinator) -> None:
        source_id, target_id = self._selected_pair(coordinator)
        output_name = f"meshping_heatmap_{source_id}_{target_id}.csv".replace("/", "_")
        output_path = EXPORT_DIR / output_name
        coordinator.export_heatmap_csv(output_path, source_id=source_id, target_id=target_id)
        self.export_notice = f"Exported heatmap to {output_path}"

    def _share_snapshot(self, coordinator: Coordinator) -> None:
        profile = coordinator.settings.usage_profile
        rows = [
            f"meshping support summary ({profile})",
            f"health score: {health_score(list(coordinator.matrix.iter_cells()), profile)}/100",
        ]
        if coordinator.split_brain:
            rows.append(f"split-brain diagnosis: {coordinator.split_brain.diagnosis}")
        for cell in sorted(
            coordinator.matrix.iter_cells(),
            key=lambda item: (item.loss_pct, item.p99 or 0.0, item.p50 or 0.0),
            reverse=True,
        )[:8]:
            rows.append(support_summary(cell, profile))
        copied = copy_text("\n".join(rows))
        self.export_notice = "Copied support summary to clipboard" if copied else "Clipboard unavailable on this system"

    def _toggle_mute(self, coordinator: Coordinator) -> None:
        _, target_id = self._selected_pair(coordinator)
        if target_id in self.muted_targets:
            self.muted_targets.remove(target_id)
            self.export_notice = f"Unmuted {target_id}"
        else:
            self.muted_targets.add(target_id)
            self.export_notice = f"Muted {target_id}"

    def _dismiss_welcome(self) -> None:
        self.show_welcome = False
        WELCOME_FILE.parent.mkdir(parents=True, exist_ok=True)
        WELCOME_FILE.write_text("seen\n", encoding="utf-8")

    def _is_muted(self, source_id: str, target_id: str) -> bool:
        return source_id in self.muted_targets or target_id in self.muted_targets
