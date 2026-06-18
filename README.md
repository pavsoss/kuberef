# Kuberef
![PyPI - Version](https://img.shields.io/pypi/v/kuberef?color=blue)
![Python Version](https://img.shields.io/pypi/pyversions/kuberef)
![CI Status](https://github.com/hudazaan/kuberef/actions/workflows/ci.yaml/badge.svg)

**Kuberef** is a lightweight, cloud-native CLI tool designed to audit Kubernetes Secret references before you deploy. It bridges the gap between static YAML manifests and your live cluster state, preventing "silent failures" caused by missing secrets or incorrect data keys.

---


## Features

- **Batch & Recursive Spec Discovery**: Automatically scans single files or entire directories for Kubernetes resources including `Deployments`, `StatefulSets`, `Jobs`, and `CronJobs` to find nested Pod specifications.

- **Deep-Key Validation**: Verifies not only that a Secret exists, but that the specific keys required are present in the Secret's data, preventing runtime container crashes.

- **Comprehensive Pattern Matching**: Audits all common Secret reference patterns, including `env.valueFrom`, bulk `envFrom` loads, `volumes` (Secret mounts), and `imagePullSecrets`.

- **Live Cluster Auditing**: Performs real-time cross-referencing against the live Kubernetes API using your active `kubeconfig` context.

- **Pre-Flight Environment Checks**: Validates cluster connectivity and ensures the target namespace exists before executing the audit to prevent false positives.

- **Global Automation Reporting**: Built with `Typer` to provide aggregate summary statistics accross multiple files and standard exit codes (0 for success, 1 for failures/warnings) to automatically break pipeline builds on misconfigurations.

- **Rich Terminal UI**: Utilizes the `Rich` library to deliver a clean, color-coded terminal interface with clear PASS/FAIL/WARNING status tables for every file scanned.

---

## Installation

### From PyPI (Recommended)

Install the tool globally using pip:

```bash
pip install kuberef
```

### From Source (Development)

If you want to run the tool from source or contribute:

```bash
git clone https://github.com/hudazaan/kuberef.git
cd kuberef
poetry install
poetry run kuberef path/to/your/k8s-manifest.yaml
```

### Using Docker (Containerized)

If you don't want to install Python locally, you can run Kuberef as a container. You must mount your local `kubeconfig` and the directory containing your manifests.

Build the image locally:

```bash
docker build -t kuberef https://github.com/hudazaan/kuberef.git
```

Run the audit: 

```bash
# Linux / macOS (zsh, bash)
docker run -it --rm --network="host" -v ~/.kube/config:/root/.kube/config -v "$(pwd):/app" kuberef /app

# Windows (PowerShell)
docker run -it --rm --network="host" -v "${HOME}/.kube/config:/root/.kube/config" -v "C:/PATH/TO/YOUR/MANIFESTS:/app" kuberef /app
```

Verification Commands (For Debugging): 

```
# Inspect package
pip show kuberef

# Run as a module
python -m kuberef --help
```

---

## Usage

Audit a single manifest against the `default` namespace:

```bash
kuberef deployment.yaml
```

Audit an entire directory of manifests: 

```bash
kuberef ./k8s-manifests/
```

Audit a specific namespace by using `-n` or `--namespace` flag to validate secrets: 

```bash
kuberef deployment.yaml --namespace production
```

General Syntax to add path to your Kubernetes manifest:

```bash
kuberef <YOUR_FILE>.yaml --namespace <YOUR_NAMESPACE>
```

**Example Output**: 

![Audit](https://raw.githubusercontent.com/hudazaan/kuberef/main/docs/images/audit-kuberef.png)

### Watch Mode

Stay running and re-audit automatically whenever a `.yaml` or `.yml` file changes:

```bash
kuberef deployment.yaml --watch
kuberef ./k8s-manifests/ -w
```

Press `Ctrl+C` to stop.

---

## Technical Architecture

- **Recursive Discovery Engine**: Implements a depth-first search to locate Pod specifications across all resource types (`Deployments`, `Jobs`, `CronJobs`, etc).
- **Live Validation**: Interfaces with the `kubernetes` Python client to perform real-time `read_namespaced_secret` calls for existence and key-level verification.
- **Stream Parser**: Leverages `PyYAML` and `safe_load_all` to parse multi-document manifests in a single pass.
- **Directory Processing Engine**: Implements a file-system crawler that identifies and filters YAML manifests for batch processing across directories.
- **CLI Framework**: Built on `Typer` to provide a high-performance interface with accumulated state counters for global multi-file reporting and standard Unix exit codes for automation.
- **CI/CD Pipeline**: Integrated with GitHub Actions to automatically build and test the tool on every code push, ensuring production readiness on Cloud-hosted runners.
- **Containerization**: Multi-stage Docker build optimized for minimal image size.

---

## Testing

Kuberef includes a suite of unit tests to ensure the recursive discovery engine and parser remain stable. These tests use `pytest` and mock data to verify logic without requiring a live cluster.

To run the tests:
```bash
poetry run pytest
```

**Verification Results**:

- **Recursive Discovery**: Confirms secrets are found deep within nested controllers.
- **Resilience**: Ensures the tool handles empty or non-Kubernetes YAML gracefully.

---

## 🤝 Contributing

Contributions are welcome!

To start contributing, please read [CONTRIBUTING.md](https://github.com/hudazaan/kuberef/blob/main/CONTRIBUTING.md).

See [Issues](https://github.com/hudazaan/kuberef/issues) to get started. 

---

### 📚 Documentation

Useful places to update while working on issues:

- Getting started locally : **[Setup Guide](https://github.com/hudazaan/kuberef#installation)** 
- About the Project: **[DOCUMENTATION.md](https://github.com/hudazaan/kuberef/blob/main/DOCUMENTATION.md)**
- Test Manifests: **[test-manifests/](https://github.com/hudazaan/kuberef/tree/main/test-manifests)**

---

## 📄 License

Distributed under the MIT License. [See LICENSE](./LICENSE) for more information.

---

## Author 

Built with ❤️ by **Huda Naaz**

---
