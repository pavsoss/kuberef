import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

console = Console()

YAML_SUFFIXES = {".yaml", ".yml"}


class YamlAuditHandler(FileSystemEventHandler):
    """This Triggers a re-audit whenever a .yaml/.yml file is modified or created."""

    def __init__(self, audit_callback: Callable[[Path], None]):
        super().__init__()
        self.audit_callback = audit_callback

    def _is_yaml(self, path: str) -> bool:
        return Path(path).suffix.lower() in YAML_SUFFIXES

    def on_modified(self, event):
        if not event.is_directory and self._is_yaml(event.src_path):
            console.print(f"\n[bold blue]⟳ Change detected:[/bold blue] {event.src_path}")
            self.audit_callback(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory and self._is_yaml(event.src_path):
            console.print(f"\n[bold blue]⟳ New file detected:[/bold blue] {event.src_path}")
            self.audit_callback(Path(event.src_path))


def run_watch_mode(watch_path: Path, audit_callback: Callable[[Path], None]) -> None:
    """
    - Starts the filesystem watcher on watch_path.
    - Calls audit_callback(path) on every .yaml/.yml change/create.
    - Blocks until Ctrl+C.
    """
    # Determine what to watch — always watch the directory
    watch_dir = watch_path if watch_path.is_dir() else watch_path.parent

    handler = YamlAuditHandler(audit_callback)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    console.print(f"\n[bold green]Watch mode active.[/bold green] Monitoring: [cyan]{watch_dir}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[bold yellow]Watch mode stopped.[/bold yellow]")

    observer.join()
