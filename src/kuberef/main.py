import typer
import yaml
from pathlib import Path
from typing import List, Dict, Any, Set
from rich.console import Console
from rich.table import Table
from kubernetes import client, config
from kubernetes.client.rest import ApiException

app = typer.Typer()
console = Console()


def find_pod_specs(data: Any) -> List[Dict[str, Any]]:
    """Recursively finds all Pod 'spec' blocks (handles Deployments, Jobs, etc.)."""
    specs = []
    if isinstance(data, dict):
        if "containers" in data and isinstance(data["containers"], list):
            specs.append(data)
        for value in data.values():
            specs.extend(find_pod_specs(value))
    elif isinstance(data, list):
        for item in data:
            specs.extend(find_pod_specs(item))
    return specs

def get_secret_refs(pod_specs: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Maps secret names to the specific keys they need to provide from Pod specs."""
    all_refs = {}

    def add_ref(name: str, key: str = None):
        if not name:
            return
        if name not in all_refs:
            all_refs[name] = set()
        if key:
            all_refs[name].add(key)

    for spec in pod_specs:
        containers = spec.get("containers", []) + spec.get("initContainers", [])
        for c in containers:
            for env in c.get("env", []):
                if "valueFrom" in env and "secretKeyRef" in env["valueFrom"]:
                    ref = env["valueFrom"]["secretKeyRef"]
                    add_ref(ref.get("name"), ref.get("key"))
            for ef in c.get("envFrom", []):
                if "secretRef" in ef:
                    add_ref(ef["secretRef"].get("name"))

        for vol in spec.get("volumes", []):
            if "secret" in vol:
                add_ref(vol.get("secret", {}).get("secretName"))

        for ps in spec.get("imagePullSecrets", []):
            add_ref(ps.get("name"))

    return all_refs

def preprocess_manifest(doc: Any) -> Dict[str, Any]:
    """Dynamically scans incoming resource schemas and extracts the Pod specification."""
    if not isinstance(doc, dict):
        return None
    return {
        "kind": doc.get("kind", "UnknownResource"),
        "name": doc.get("metadata", {}).get("name", "unknown-name"),
        "pod_specs": find_pod_specs(doc),
        "raw_doc": doc
    }

def preprocess_manifests(docs: List[Any]) -> List[Dict[str, Any]]:
    """Transforms raw YAML documents into normalized manifests with extracted pod specs."""
    processed = []
    for doc in docs:
        if doc:
            p_doc = preprocess_manifest(doc)
            if p_doc and p_doc["pod_specs"]:
                processed.append(p_doc)
    return processed

def run_audit(files_to_scan: List[Path], namespace: str, v1: Any, quiet: bool = False) -> int:
    """
    Core audit logic. Scans the given files against the live cluster.
    Returns exit code: 0 for clean, 1 for failures/warnings.
    """
    global_passed, global_failed, global_warnings = 0, 0, 0

    for yaml_file in files_to_scan:
        with open(yaml_file, "r") as f:
            try:
                docs = list(yaml.safe_load_all(f))
            except yaml.YAMLError:
                console.print(
                    f"[bold red]Error:[/bold red] Invalid YAML format in {yaml_file.name}. Skipping..."
                )
                continue

        processed_docs = preprocess_manifests(docs)
        if not processed_docs:
            continue

        combined_refs = {}
        secret_resources = {}
        for p_doc in processed_docs:
            refs = get_secret_refs(p_doc["pod_specs"])
            kind_name = f'{p_doc["kind"]}/{p_doc["name"]}'
            for name, keys in refs.items():
                combined_refs.setdefault(name, set()).update(keys)
                secret_resources.setdefault(name, set()).add(kind_name)

        if not combined_refs:
            continue

        table = Table(title=f"Security Audit: {yaml_file.name}")
        table.add_column("Secret Name", style="cyan")
        table.add_column("Status", justify="left")
        table.add_column("Found In", style="dim")

        for name, keys in combined_refs.items():
            resources_str = ", ".join(sorted(secret_resources.get(name, set())))
            try:
                secret = v1.read_namespaced_secret(name, namespace)
                if keys:
                    existing_keys = (secret.data or {}).keys()
                    missing = [k for k in keys if k not in existing_keys]
                    if missing:
                        table.add_row(name, f"[bold yellow]KEY MISSING: {', '.join(missing)}[/bold yellow]", resources_str)
                        global_warnings += 1
                    else:
                        table.add_row(name, "[bold green]PASS[/bold green]", resources_str)
                        global_passed += 1
                else:
                    table.add_row(name, "[bold green]PASS (Found)[/bold green]", resources_str)
                    global_passed += 1
            except ApiException as e:
                if e.status == 404:
                    table.add_row(name, "[bold red]FAIL (Secret Missing)[/bold red]", resources_str)
                    global_failed += 1
                else:
                    table.add_row(name, f"[dim]Error {e.status}[/dim]", resources_str)
                    global_failed += 1

        if not quiet:
            console.print(table)

    console.print("\n" + "━" * 30)
    console.print("[bold underline]AUDIT SUMMARY[/bold underline]\n")
    console.print(f"📂 Files Scanned: {len(files_to_scan)}")
    console.print(f"✅ Total Passed:   [green]{global_passed}[/green]")
    console.print(f"❌ Total Failed:   [red]{global_failed}[/red]")
    console.print(f"⚠️  Total Warnings: [yellow]{global_warnings}[/yellow]")
    console.print("━" * 30 + "\n")

    return 1 if (global_failed > 0 or global_warnings > 0) else 0


@app.command()
def audit(
    path_str: str = typer.Argument(..., help="Path to K8s YAML file or directory"),
    namespace: str = typer.Option("default", "--namespace", "-n"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silence per-file status tables and print only the summary"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stay running and re-audit on every .yaml/.yml file change."),
):
    """
Deep audit: Checks files or directories against Cluster, Namespace,
and Secret keys.

Examples:
  kuberef deployment.yaml             # Scan a single manifest file
  kuberef ./k8s-manifests/            # Scan an entire directory
  kuberef deployment.yaml --watch     # Re-audit automatically on file changes
  kuberef ./k8s-manifests/ -w         # Watch an entire directory

"""
    target_path = Path(path_str)

    files_to_scan: List[Path] = []
    if target_path.is_dir():
        files_to_scan = list(target_path.rglob("*.yaml")) + list(target_path.rglob("*.yml"))
    elif target_path.is_file():
        files_to_scan = [target_path]
    else:
        console.print(f"[bold red]Error:[/bold red] Path {path_str} not found!")
        raise typer.Exit(1)

    if not files_to_scan:
        console.print(f"[yellow]No YAML files found at {path_str}[/yellow]")
        return

    try:
        config.load_kube_config()
        _, active_context = config.list_kube_config_contexts()
        cluster_name = active_context["name"]
        v1 = client.CoreV1Api()
        v1.read_namespace(name=namespace)
        console.print(f"[bold blue]Target Cluster:[/bold blue] {cluster_name}")
    except Exception as e:
        console.print(f"[bold red]Pre-flight Error:[/bold red] {str(e)}")
        raise typer.Exit(1)

    exit_code = run_audit(files_to_scan, namespace, v1, quiet=quiet)

    if watch:
        from kuberef.watcher import run_watch_mode

        def _on_change(changed_path: Path) -> None:
            if target_path.is_dir():
                updated_files = list(target_path.rglob("*.yaml")) + list(target_path.rglob("*.yml"))
            else:
                updated_files = [changed_path]
            run_audit(updated_files, namespace, v1, quiet=quiet)

        run_watch_mode(target_path, _on_change)
    else:
        raise typer.Exit(exit_code)


def start():
    app()


if __name__ == "__main__":
    start()
