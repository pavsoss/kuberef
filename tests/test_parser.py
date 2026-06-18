import pytest
import yaml
from unittest.mock import patch, MagicMock
from kuberef.main import get_secret_refs, preprocess_manifest, preprocess_manifests, audit
from typer.testing import CliRunner
from kubernetes.client.rest import ApiException
from kuberef.main import app
import os

def test_preprocess_manifest_preserves_metadata():
    """Test that preprocess_manifest preserves kind/name and extracts pod_specs for a Rollout-style doc."""
    doc = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Rollout",
        "metadata": {
            "name": "sample-rollout"
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "app",
                        "env": [{
                            "name": "DB_PASS",
                            "valueFrom": {"secretKeyRef": {"name": "db-secret", "key": "password"}}
                        }]
                    }]
                }
            }
        }
    }
    p_doc = preprocess_manifest(doc)
    assert p_doc is not None
    assert p_doc["kind"] == "Rollout"
    assert p_doc["name"] == "sample-rollout"
    assert len(p_doc["pod_specs"]) == 1
    assert p_doc["pod_specs"][0]["containers"][0]["name"] == "app"

def test_get_secret_refs_new_signature():
    """Test that get_secret_refs(pod_specs) works on the new signature."""
    pod_specs = [
        {
            "containers": [{
                "name": "app",
                "env": [{
                    "name": "DB_PASS",
                    "valueFrom": {"secretKeyRef": {"name": "db-secret", "key": "password"}}
                }]
            }]
        }
    ]
    refs = get_secret_refs(pod_specs)
    assert "db-secret" in refs
    assert "password" in refs["db-secret"]

def test_empty_manifest():
    """Ensure the tool doesn't crash on empty or non-k8s YAML."""
    manifest = {"random": "data"}
    p_doc = preprocess_manifest(manifest)
    assert p_doc is not None
    refs = get_secret_refs(p_doc.get("pod_specs", []))
    assert refs == {}

def test_combined_refs_deduplication():
    """Test combined_refs deduplication across multiple docs in one file."""
    multi_doc_yaml = """
---
kind: Deployment
metadata:
  name: deploy1
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: DB_PASS
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: password
---
kind: Pod
metadata:
  name: pod1
spec:
  containers:
  - name: worker
    env:
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: token
"""
    docs = list(yaml.safe_load_all(multi_doc_yaml))
    processed_docs = preprocess_manifests(docs)
    
    combined_refs = {}
    for p_doc in processed_docs:
        refs = get_secret_refs(p_doc["pod_specs"])
        for name, keys in refs.items():
            combined_refs.setdefault(name, set()).update(keys)

    assert "db-secret" in combined_refs
    assert "password" in combined_refs["db-secret"]
    assert "token" in combined_refs["db-secret"]
    assert len(combined_refs) == 1

@patch("kuberef.main.client.CoreV1Api")
@patch("kuberef.main.config.load_kube_config")
@patch("kuberef.main.config.list_kube_config_contexts")
def test_audit_with_mock_client(mock_list_contexts, mock_load_config, mock_core_v1_api, tmp_path):
    """Test the audit function with a mocked kubernetes client."""
    mock_list_contexts.return_value = (None, {"name": "Test-Cluster"})
    mock_v1 = MagicMock()
    mock_core_v1_api.return_value = mock_v1
    
    # Setup mock secret response
    mock_secret = MagicMock()
    mock_secret.data = {"password": "base64data"}
    mock_v1.read_namespaced_secret.return_value = mock_secret
    
    # Create a temporary manifest file
    manifest_path = tmp_path / "test-manifest.yaml"
    manifest_path.write_text("""
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
  - name: test-container
    env:
    - name: TEST_ENV
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: password
""")

    runner = CliRunner()
    result = runner.invoke(app, [str(manifest_path)])
    
    # It should succeed because the secret and key exist in the mock
    assert result.exit_code == 0
    mock_v1.read_namespaced_secret.assert_called_once_with("db-secret", "default")

def test_invalid_yaml_handling():
    """Test that the audit command gracefully handles malformed YAML files without crashing."""
    import os
    from unittest.mock import patch, MagicMock
    from typer.testing import CliRunner
    from kuberef.main import app

    runner = CliRunner()
    
    with patch("kuberef.main.config.load_kube_config") as mock_load, \
         patch("kuberef.main.config.list_kube_config_contexts") as mock_contexts, \
         patch("kuberef.main.client.CoreV1Api") as mock_api_class:
        
        mock_contexts.return_value = (None, {"name": "mock-cluster"})
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        
        # Mock read_namespaced_secret to return correct Kubernetes secret objects
        def mock_read_secret(name, namespace=None):
            secret_data = {
                "registry-creds": {},
                "db-secret": {"password": "some-password-hash"},
                "api-keys": {},
                "ssl-certs": {},
                "controller-level-secret": {"api-token": "some-token"},
                "nested-app-secret": {"password": "some-password"}
            }
            if name in secret_data:
                secret = MagicMock()
                secret.data = secret_data[name]
                return secret
            from kubernetes.client.rest import ApiException
            raise ApiException(status=404, reason="Not Found")
            
        mock_api.read_namespaced_secret.side_effect = mock_read_secret
        
        # Resolve test-manifests to an absolute path
        test_manifests_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "test-manifests")
        )
        
        result = runner.invoke(app, [test_manifests_dir])
        
        # The tool should finish with exit code 0 or 1, and not crash with an exception.
        assert result.exit_code in (0, 1)
        # It should contain a clear error/warning message about malformed-pod.yaml.
        assert "Invalid YAML" in result.output
        assert "malformed-pod.yaml" in result.output


def test_quiet_mode():
    """Test that the audit command suppresses per-file tables when the quiet option is enabled."""
    import os
    from unittest.mock import patch, MagicMock
    from typer.testing import CliRunner
    from kuberef.main import app

    runner = CliRunner()
    
    with patch("kuberef.main.config.load_kube_config") as mock_load, \
         patch("kuberef.main.config.list_kube_config_contexts") as mock_contexts, \
         patch("kuberef.main.client.CoreV1Api") as mock_api_class:
        
        mock_contexts.return_value = (None, {"name": "mock-cluster"})
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        
        # Mock read_namespaced_secret
        def mock_read_secret(name, namespace=None):
            secret = MagicMock()
            secret.data = {}
            return secret
            
        mock_api.read_namespaced_secret.side_effect = mock_read_secret
        
        test_manifests_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "test-manifests")
        )
        
        # Test short option -q
        result_q = runner.invoke(app, [test_manifests_dir, "-q"])
        assert result_q.exit_code in (0, 1)
        assert "Security Audit:" not in result_q.output
        assert "AUDIT SUMMARY" in result_q.output
        
        # Test long option --quiet
        result_quiet = runner.invoke(app, [test_manifests_dir, "--quiet"])
        assert result_quiet.exit_code in (0, 1)
        assert "Security Audit:" not in result_quiet.output
        assert "AUDIT SUMMARY" in result_quiet.output

def test_complex_pod_secret_references():
    """
    Verifies that the parser extracts all 4 core Secret reference patterns
    (env, envFrom, volumes, and imagePullSecrets) from a real manifest file.
    """
    # 1. Safely locate the test-manifests directory relative to this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    manifest_path = os.path.join(project_root, "test-manifests", "complex-pod.yaml")
    
    # 2. Read and parse the raw static YAML file from disk
    with open(manifest_path, "r") as file:
        manifest_data = yaml.safe_load(file)
        
    # 3. Pass the parsed dictionary data to the Kuberef discovery engine
    p_doc = preprocess_manifest(manifest_data)
    discovered_secrets = get_secret_refs(p_doc["pod_specs"])
    
    # 4. Assert that all 4 expected target secrets are extracted properly
    assert "registry-creds" in discovered_secrets, "Failed to extract secret from imagePullSecrets"
    assert "db-secret" in discovered_secrets, "Failed to extract secret from env.valueFrom"
    assert "api-keys" in discovered_secrets, "Failed to extract secret from envFrom"
    assert "ssl-certs" in discovered_secrets, "Failed to extract secret from volumes"
