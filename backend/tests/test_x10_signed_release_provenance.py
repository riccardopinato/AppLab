"""X10-031 unit tests: synthetic artifact and inspector responses, not signed APKs."""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

SOURCE=Path(__file__).resolve().parents[2]/"scripts"/"x10_signed_release_provenance.py"
SPEC=importlib.util.spec_from_file_location("x10_signed_release_provenance",SOURCE)
gate=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

SHA="a"*40
ENGINE="b"*40
CERT="c"*64
REPO="example/app"


def setup(tmp_path, *, kind="APK"):
    raw=b"synthetic artifact bytes; no actual APK signature"
    path=tmp_path/("app.aab" if kind=="AAB" else "app.apk")
    path.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    request={
        "schema_version":1,"repository":REPO,"source_sha":SHA,
        "trusted_applab_sha":ENGINE,"package_id":"com.example.app",
        "version_name":"1.0","version_code":"42",
        "expected_signing_cert_sha256":CERT,"workflow_run_id":12345,
        "workflow_repository":REPO,
        "artifacts":[{"kind":kind,"abi":"bundle" if kind=="AAB" else "arm64-v8a",
                      "relative_path":path.name,"sha256":digest,
                      "size_bytes":len(raw),"artifact_id":987,
                      "artifact_url":f"https://github.com/{REPO}/actions/runs/12345/artifacts/987"}],
    }
    contract={"repository":REPO,"resolved_sha":SHA,"trusted_applab_sha":ENGINE,
              "apk":{"sha256":digest,"size_bytes":len(raw),
                     "package_id":"com.example.app","version_name":"1.0",
                     "version_code":"42","signing_cert_sha256":CERT,
                     "build_variant":"release"}}
    return request,contract


def inspect_apk(path):
    return {"package_id":"com.example.app","version_name":"1.0","version_code":"42"}


def inspect_signer(path):
    return {"certificate_sha256":CERT}


def inspect_aab(path):
    return {"package_id":"com.example.app","version_name":"1.0",
            "version_code":"42","certificate_sha256":CERT,"signature_verified":True}


def run(req,contract,root,**overrides):
    opts=dict(artifact_root=root,apk_identity=inspect_apk,
              apk_signing=inspect_signer,aab_inspector=inspect_aab)
    opts.update(overrides)
    return gate.assess(req,contract,**opts)


def test_byte_bound_apk_remains_uncertified(tmp_path):
    req,contract=setup(tmp_path)
    out=run(req,contract,tmp_path)
    assert out["state"]=="PENDING_INDEPENDENT_REMOTE_AND_DEVICE_EVIDENCE"
    assert out["store_ready"] is False
    assert out["artifact_urls_verified_remotely"] is False
    assert out["artifacts"][0]["abi"]=="arm64-v8a"


def test_mutated_apk_bytes_rejected(tmp_path):
    req,contract=setup(tmp_path)
    (tmp_path/"app.apk").write_bytes(b"tampered")
    with pytest.raises(gate.ProvenanceGateError,match="ARTIFACT_BYTES_MISMATCH"):
        run(req,contract,tmp_path)


def test_contract_drift_rejected(tmp_path):
    req,contract=setup(tmp_path)
    contract["resolved_sha"]="e"*40
    with pytest.raises(gate.ProvenanceGateError,match="BUILD_CONTRACT_SOURCE_MISMATCH"):
        run(req,contract,tmp_path)


def test_unsigned_apk_rejected(tmp_path):
    req,contract=setup(tmp_path)
    with pytest.raises(gate.ProvenanceGateError,match="APK_SIGNING_CERT_MISMATCH"):
        run(req,contract,tmp_path,apk_signing=lambda path:{"certificate_sha256":""})


def test_debug_apk_cannot_claim_signed_release(tmp_path):
    req,contract=setup(tmp_path)
    contract["apk"]["build_variant"]="debug"
    with pytest.raises(gate.ProvenanceGateError,match="CANONICAL_APK_BUILD_CONTRACT_MISMATCH"):
        run(req,contract,tmp_path)


def test_wrong_version_rejected(tmp_path):
    req,contract=setup(tmp_path)
    req["version_code"]="43"
    with pytest.raises(gate.ProvenanceGateError,match="APK_MANIFEST_IDENTITY_MISMATCH"):
        run(req,contract,tmp_path)


def test_stale_artifact_url_rejected(tmp_path):
    req,contract=setup(tmp_path)
    req["artifacts"][0]["artifact_url"]="https://github.com/example/app/actions/runs/2/artifacts/987"
    with pytest.raises(gate.ProvenanceGateError,match="UNBOUND_ARTIFACT_URL"):
        run(req,contract,tmp_path)


def test_central_applab_run_url_binds_to_workflow_repo(tmp_path):
    req,contract=setup(tmp_path)
    req["workflow_repository"]="riccardopinato/AppLab"
    req["artifacts"][0]["artifact_url"]="https://github.com/riccardopinato/AppLab/actions/runs/12345/artifacts/987"
    out=run(req,contract,tmp_path)
    assert out["workflow_repository"]=="riccardopinato/AppLab"
    assert out["store_ready"] is False


def test_untrusted_run_repository_rejected(tmp_path):
    req,contract=setup(tmp_path)
    req["workflow_repository"]="malicious/unrelated"
    with pytest.raises(gate.ProvenanceGateError,match="UNTRUSTED_WORKFLOW_REPOSITORY"):
        run(req,contract,tmp_path)


def test_missing_or_invalid_aab_verifier_fails_closed(tmp_path):
    req,contract=setup(tmp_path,kind="AAB")
    with pytest.raises(gate.ProvenanceGateError,match="AAB_VERIFIER_NOT_CONFIGURED"):
        run(req,contract,tmp_path,aab_inspector=None)
    with pytest.raises(gate.ProvenanceGateError,match="AAB_SIGNATURE_OR_IDENTITY_NOT_VERIFIED"):
        run(req,contract,tmp_path,aab_inspector=lambda path:dict(inspect_aab(path),signature_verified=False))


def test_signed_aab_fixture_still_not_store_ready(tmp_path):
    req,contract=setup(tmp_path,kind="AAB")
    result=run(req,contract,tmp_path)
    assert result["store_ready"] is False
    assert result["artifacts"][0]["kind"]=="AAB"


def test_scope_and_duplicate_rejected(tmp_path):
    req,contract=setup(tmp_path)
    req["artifacts"][0]["abi"]="bundle"
    with pytest.raises(gate.ProvenanceGateError,match="INVALID_ARTIFACT_SCOPE"):
        run(req,contract,tmp_path)
    req,contract=setup(tmp_path)
    req["artifacts"].append(copy.deepcopy(req["artifacts"][0]))
    with pytest.raises(gate.ProvenanceGateError,match="DUPLICATE_ARTIFACT_SCOPE"):
        run(req,contract,tmp_path)


def test_path_escape_and_symlink_rejected(tmp_path):
    req,contract=setup(tmp_path)
    req["artifacts"][0]["relative_path"]="../app.apk"
    with pytest.raises(gate.ProvenanceGateError,match="UNSAFE_ARTIFACT_PATH"):
        run(req,contract,tmp_path)
    req,contract=setup(tmp_path)
    (tmp_path/"app.apk").unlink()
    (tmp_path/"app.apk").symlink_to(tmp_path/"outside")
    with pytest.raises(gate.ProvenanceGateError,match="UNAVAILABLE_OR_UNSAFE_ARTIFACT"):
        run(req,contract,tmp_path)
