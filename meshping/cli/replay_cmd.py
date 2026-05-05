from __future__ import annotations

import asyncio
import contextlib
import os
import queue
import select
from pathlib import Path
import sys
import termios
import threading
import tty

import click
from rich.console import Group
from rich.console import Console
from rich.live import Live

from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator
from meshping.storage.replay import ReplayController, ReplaySession
from meshping.ui.matrix_view import MeshDashboard
from meshping.ui.replay_view import render_replay_progress


@click.command("replay")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--speed", default="1x", show_default=True)
@click.option("--seek", help="Skip replay events before HH:MM:SS offset.")
@click.option("--once", is_flag=True, help="Render final state without live playback.")
def replay_command(path: Path, speed: str, seek: str | None, once: bool) -> None:
    """Replay a recorded .mpr session."""
    session = ReplaySession.from_file(path)
    asyncio.run(
        _run_replay(
            session,
            speed=_parse_speed(speed),
            seek_s=_parse_seek(seek),
            once=once,
        )
    )


async def _run_replay(
    session: ReplaySession,
    *,
    speed: float,
    seek_s: float,
    once: bool,
) -> None:
    coordinator = Coordinator(nodes=session.nodes, settings=Settings())
    if once:
        start = session.events[0].timestamp_s if session.events else 0.0
        for event in session.events:
            if event.timestamp_s - start >= seek_s:
                coordinator.ingest(event.result)
        console = Console()
        console.print(MeshDashboard(console=console).render(coordinator))
        coordinator.stop()
        return

    console = Console()
    dashboard = MeshDashboard(console=console)
    controller = ReplayController(
        speed=speed,
        total_duration_s=session.total_duration_s,
    )
    start_index = session.rebuild_until_offset(coordinator, seek_s)
    controller.position_s = seek_s
    reader = _ReplayKeyReader()
    worker = asyncio.create_task(
        _feed_replay(
            session,
            coordinator,
            controller,
            start_index=start_index,
        )
    )
    try:
        reader.start()
        with Live(
            Group(
                dashboard.render(coordinator),
                render_replay_progress(
                    current_offset_s=controller.position_s,
                    total_duration_s=controller.total_duration_s,
                    speed=controller.speed,
                    paused=controller.paused,
                    markers=session.progress_markers(),
                ),
            ),
            console=console,
            refresh_per_second=8,
        ) as live:
            while not controller.quit_requested and not coordinator.stop_event.is_set():
                _handle_replay_keys(reader, controller)
                live.update(
                    Group(
                        dashboard.render(coordinator),
                        render_replay_progress(
                            current_offset_s=controller.position_s,
                            total_duration_s=controller.total_duration_s,
                            speed=controller.speed,
                            paused=controller.paused,
                            markers=session.progress_markers(),
                        ),
                    )
                )
                await asyncio.sleep(0.1)
    finally:
        controller.quit_requested = True
        controller.changed.set()
        reader.stop()
        coordinator.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


def _parse_speed(value: str) -> float:
    raw = value.strip().lower().removesuffix("x")
    try:
        speed = float(raw)
    except ValueError as exc:
        raise click.BadParameter("speed must look like 1x or 2x") from exc
    if speed <= 0:
        raise click.BadParameter("speed must be greater than zero")
    return speed


def _parse_seek(value: str | None) -> float:
    if not value:
        return 0.0
    parts = value.split(":")
    if len(parts) != 3:
        raise click.BadParameter("seek must be HH:MM:SS")
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError as exc:
        raise click.BadParameter("seek must be HH:MM:SS") from exc
    return hours * 3600 + minutes * 60 + seconds


async def _feed_replay(
    session: ReplaySession,
    coordinator: Coordinator,
    controller: ReplayController,
    *,
    start_index: int,
) -> None:
    index = start_index
    current_ts = session.start_ts + controller.position_s
    while index < len(session.events) and not controller.quit_requested:
        if controller.pending_seek_s is not None:
            index = session.rebuild_until_offset(coordinator, controller.pending_seek_s)
            controller.position_s = controller.pending_seek_s
            current_ts = session.start_ts + controller.position_s
            controller.pending_seek_s = None
            controller.state = "PLAYING"
            controller.changed.clear()
            continue
        if controller.paused:
            try:
                await asyncio.wait_for(controller.changed.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            controller.changed.clear()
            continue
        event = session.events[index]
        delay = max(0.0, event.timestamp_s - current_ts) / controller.speed
        try:
            await asyncio.wait_for(controller.changed.wait(), timeout=delay)
            controller.changed.clear()
            continue
        except asyncio.TimeoutError:
            coordinator.ingest(event.result)
            controller.position_s = event.timestamp_s - session.start_ts
            current_ts = event.timestamp_s
            index += 1
    coordinator.stop()


class _ReplayKeyReader:
    def __init__(self) -> None:
        self._keys: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fd: int | None = None
        self._old_settings = None
        self._prompting = threading.Event()

    def start(self) -> None:
        if not sys.stdin.isatty():
            return
        self._thread = threading.Thread(target=self._loop, name="meshping-replay-keys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)

    def drain(self) -> list[str]:
        keys: list[str] = []
        while True:
            try:
                keys.append(self._keys.get_nowait())
            except queue.Empty:
                return keys

    def prompt_seek(self) -> str | None:
        if self._fd is None or self._old_settings is None:
            return None
        self._prompting.set()
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
        try:
            return input("Goto HH:MM:SS: ").strip()
        except EOFError:
            return None
        finally:
            tty.setcbreak(self._fd)
            self._prompting.clear()

    def _loop(self) -> None:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        self._fd = fd
        self._old_settings = old_settings
        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                if self._prompting.is_set():
                    continue
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue
                char = os.read(fd, 1).decode("utf-8", errors="ignore")
                if char == "\x1b":
                    seq = os.read(fd, 2).decode("utf-8", errors="ignore")
                    if seq == "[C":
                        self._keys.put("RIGHT")
                    elif seq == "[D":
                        self._keys.put("LEFT")
                    continue
                if char == " ":
                    self._keys.put("SPACE")
                elif char in {"q", "g"}:
                    self._keys.put(char)
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _handle_replay_keys(reader: _ReplayKeyReader, controller: ReplayController) -> None:
    for key in reader.drain():
        if key == "SPACE":
            controller.toggle_pause()
        elif key == "RIGHT":
            controller.set_speed(controller.speed * 2)
        elif key == "LEFT":
            controller.set_speed(controller.speed / 2)
        elif key == "q":
            controller.quit_requested = True
            controller.changed.set()
        elif key == "g":
            raw = reader.prompt_seek()
            if raw:
                try:
                    controller.seek(_parse_seek(raw))
                except click.BadParameter:
                    continue
