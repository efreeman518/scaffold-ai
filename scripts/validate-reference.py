#!/usr/bin/env python3
"""Validate the TaskFlow proof repository against this scaffold checkout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


SCAFFOLD_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK_RE = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
ACTION_REF_RE = re.compile(r"\buses:\s*([^\s@]+)@([^\s#]+)")
SHA_REF_RE = re.compile(r"^[0-9a-f]{40}$")
PROOF_ROOTS = (".scaffold/", ".github/", "deploy/", "src/", "tests/", "infra/")
# Keep in sync with validate-instructions.py CONCRETE_MODEL_PATTERN.
CONCRETE_MODEL_PATTERN = re.compile(
    r"\b(?:gpt-\d[\w.-]*|o\d-(?:mini|pro)\b|text-embedding-[\w-]+|claude-(?:opus|sonnet|haiku)[\w.-]*|gemini-\d[\w.-]*)",
    re.IGNORECASE,
)

# Evidence is conditional on what the reference app itself declares in
# .scaffold/resource-implementation.yaml: schema validation owns shape and
# enums, this file owns declared-vs-wired agreement. Each entry is
# (conditions, sentinels, paths) - conditions is an OR-list of AND-dicts over
# declared keys; when one dict fully matches, every sentinel and path in the
# entry is required. Undeclared or falsy capabilities require nothing, so a
# deliberate reference config change needs no scaffold-side edit.
CONDITIONAL_EVIDENCE: tuple[
    tuple[tuple[dict[str, object], ...], tuple[tuple[str, str], ...], tuple[str, ...]], ...
] = (
    (
        ({"applicationStyle": "switch"},),
        (
            ("src/Application/TaskFlow.Application.Contracts/ApplicationStyle.cs", "TASKFLOW_APPLICATION_STYLE"),
            ("src/Host/TaskFlow.Api/WebApplicationBuilderExtensions.cs", "ApplicationStyleResolver"),
        ),
        (),
    ),
    (
        ({"includeFlowEngine": True},),
        (
            ("src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.FlowEngine.cs", "AddFlowEngine"),
            ("src/Host/TaskFlow.Api/WebApplicationBuilderExtensions.cs", "MapFlowEngineAdmin"),
        ),
        (
            "src/Host/TaskFlow.Api/Workflows/ai-task-triage.json",
            "src/Host/TaskFlow.Api/Workflows/ai-task-decomposer.json",
            "src/Host/TaskFlow.Api/Workflows/compliance-check.json",
            "src/Infrastructure/TaskFlow.Infrastructure.Data.Migrations.SqlServer/Migrations/FlowEngine",
            "src/Infrastructure/TaskFlow.Infrastructure.Data.Migrations.PostgreSql/Migrations/FlowEngine",
            "tests/Test.Integration.FlowEngine/Test.Integration.FlowEngine.csproj",
        ),
    ),
    (
        ({"includeKeyVault": True},),
        (("src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.DataProtection.cs", "ProtectKeysWithAzureKeyVault"),),
        ("infra/modules/key-vault.bicep",),
    ),
    (
        ({"includeFunctionApp": True, "includeFlowEngine": True},),
        (("src/Host/TaskFlow.Functions/FunctionWorkflowTrigger.cs", "ProcessTaskWorkflowStart"),),
        (),
    ),
    (
        ({"includeGitHubActions": True, "includeFlowEngine": True},),
        ((".github/workflows/ci.yml", "Test.Integration.FlowEngine"),),
        (),
    ),
    (
        ({"includeGitHubActions": True, "includeAspireTests": True},),
        ((".github/workflows/ci.yml", "Test.Aspire"),),
        (),
    ),
    (
        ({"includeGitHubActions": True, "includePlaywrightUITests": True},),
        ((".github/workflows/ci.yml", "Test.PlaywrightUI"),),
        (),
    ),
    (
        ({"includeArchitectureTests": True},),
        (),
        ("tests/Test.Architecture/Test.Architecture.csproj",),
    ),
    (({"includeE2ETests": True},), (), ("tests/Test.E2E/Test.E2E.csproj",)),
    (({"includeLoadTests": True},), (), ("tests/Test.Load/Test.Load.csproj",)),
    (({"includeBenchmarkTests": True},), (), ("tests/Test.Benchmarks/Test.Benchmarks.csproj",)),
    (({"includeMutationTests": True},), (), ("tests/Test.Mutation/Test.Mutation.csproj",)),
    (({"includeAspireTests": True},), (), ("tests/Test.Aspire/Test.Aspire.csproj",)),
    (({"includePlaywrightUITests": True},), (), ("tests/Test.PlaywrightUI/Test.PlaywrightUI.csproj",)),
    (({"includeMobileTests": True},), (), ("tests/Test.Mobile/Test.Mobile.csproj",)),
    (
        ({"includeUnoUI": True}, {"includeBlazorUI": True}, {"includeReactUI": True}),
        (),
        ("tests/Test.UI/Test.UI.csproj",),
    ),
    (
        (
            {"hostingLanes": ["Azure", "NonAzure"]},
            {"hostingLanes": ["Azure", "Portable"]},
        ),
        (
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", 'LaneEnvironmentVariable = "TASKFLOW_LANE"'),
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", 'normalized.Equals("Portable"'),
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", '"PostgreSqlJsonb", "MongoDb"'),
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", 'value.Equals("Relational"'),
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", 'azure ? ["SqlServer"] : ["PostgreSql"]'),
            ("src/Shared/TaskFlow.Hosting/HostingLane.cs", 'azure ? ["Sql", "AzureAiSearch"] : ["Sql", "PgVector"]'),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "Resolve_Unset_ReturnsExactAzureProfile"),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "Resolve_NonAzure_ReturnsExactProfile"),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "Resolve_SameLaneOptIns_AreAccepted"),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "Resolve_CrossLaneValue_ThrowsDiagnostic"),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "Resolve_NonAzureAzureServiceSetting_Throws"),
            ("tests/Test.Unit/Hosting/HostingLaneContractTests.cs", "ResolveFromEnvironment_NonAzureAzureServiceSetting_Throws"),
            ("src/Host/TaskFlow.Bootstrapper/Registration/ProviderSwitchAttribute.cs", "ProviderSwitchAttribute"),
            ("src/Host/Aspire/ServiceDefaults/Extensions.cs", 'MapHealthChecks("/healthz/live"'),
            ("src/Host/Aspire/ServiceDefaults/Extensions.cs", 'MapHealthChecks("/healthz/ready"'),
            ("deploy/compose/docker-compose.yml", "Hosting__Lane: NonAzure"),
            ("infra/main.bicep", "{ name: 'Hosting__Lane', value: 'Azure' }"),
        ),
        (
            "tests/Test.Architecture/ProviderSwitchArchitectureTests.cs",
            "tests/Test.Aspire/AppHostLaneTopologyTests.cs",
            "tests/Test.Endpoints/HealthProbeContractTests.cs",
            "deploy/compose/docker-compose.yml",
            ".github/workflows/deploy-vps.yml",
        ),
    ),
    (
        ({"externalDependencyModes": {"openObserve": "deployment-only"}},),
        (
            ("src/Host/Aspire/ServiceDefaults/Extensions.cs", 'GetValue("OpenTelemetry:MetricsEnabled", true)'),
            ("src/Host/Aspire/ServiceDefaults/Extensions.cs", "logging.AddOtlpExporter();"),
            ("src/Host/Aspire/ServiceDefaults/Extensions.cs", "tracing.AddOtlpExporter();"),
            ("src/Host/TaskFlow.Api/Middleware/ProblemDetailsCorrelation.cs", 'Extensions["requestId"]'),
            ("src/Host/TaskFlow.Api/Middleware/ProblemDetailsCorrelation.cs", "activity.TraceId.ToHexString()"),
            ("src/Host/TaskFlow.Api/Middleware/ProblemDetailsCorrelation.cs", "activity.SpanId.ToHexString()"),
            ("deploy/compose/docker-compose.yml", "openobserve-data:"),
            (".github/workflows/deploy-vps.yml", "OPENOBSERVE_RETENTION_DAYS"),
            (".github/workflows/deploy-vps.yml", "telemetrygen@sha256:"),
            ("tests/Test.Unit/Infrastructure/DeploymentWorkflowContractTests.cs", "DeployVpsWorkflow_IsManualSerializedAndReversible"),
            ("tests/Test.Unit/Infrastructure/DeploymentWorkflowContractTests.cs", "ComposeLane_ExposesOnlyTheEdgeAndWaitsOnTheMigrator"),
        ),
        (
            "tests/Test.Unit/Hosting/OpenTelemetryMetricsRegistrationTests.cs",
            "tests/Test.Endpoints/GlobalExceptionHandlerTests.cs",
        ),
    ),
)

STRICT_LANE_DEFAULTS: dict[str, dict[str, str]] = {
    "Azure": {
        "databaseProvider": "SqlServer",
        "messagingProvider": "ServiceBus",
        "storageProvider": "AzureBlob",
        "readModelProvider": "Cosmos",
        "auditProvider": "AzureTable",
        "searchProvider": "Sql",
        "aiProvider": "None",
        "dataProtectionPersistence": "AzureBlob",
        "deploymentTarget": "ContainerApps",
    },
    "NonAzure": {
        "databaseProvider": "PostgreSql",
        "messagingProvider": "RabbitMq",
        "storageProvider": "S3",
        "readModelProvider": "PostgreSqlJsonb",
        "auditProvider": "Relational",
        "searchProvider": "Sql",
        "aiProvider": "None",
        "dataProtectionPersistence": "Redis",
        "deploymentTarget": "DockerCompose",
    },
}

# Required regardless of declared capabilities: the terminal handoff contract,
# the capability-status legend, and the base test suites every scaffold carries.
ALWAYS_SENTINELS: tuple[tuple[str, str], ...] = (
    ("HANDOFF.md", "workflowStatus: complete"),
    (".scaffold/REFERENCE-STATUS.md", "- `proven`:"),
    (".scaffold/REFERENCE-STATUS.md", "- `deployment-only`:"),
    (".scaffold/REFERENCE-STATUS.md", "- `documented-only`:"),
    (".scaffold/REFERENCE-STATUS.md", "- `not enabled`:"),
)

ALWAYS_PATHS: tuple[str, ...] = (
    "tests/Test.Unit/Test.Unit.csproj",
    "tests/Test.Endpoints/Test.Endpoints.csproj",
    "tests/Test.Integration/Test.Integration.csproj",
)


def tracked_markdown_files(root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", "*.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        return [root / line for line in proc.stdout.splitlines() if line]
    return sorted(path for path in root.rglob("*.md") if ".git" not in path.parts)


def link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1:raw.index(">")]
    return raw.split(maxsplit=1)[0]


def check_markdown_links(root: Path) -> list[str]:
    errors: list[str] = []
    for markdown in tracked_markdown_files(root):
        text = markdown.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK_RE.finditer(line):
                target = unquote(link_target(match.group(1)))
                path_part = target.split("#", 1)[0].split("?", 1)[0]
                if not path_part or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path_part):
                    continue
                resolved = (root / path_part.lstrip("/")) if path_part.startswith("/") else (markdown.parent / path_part)
                if not resolved.resolve().exists():
                    rel = markdown.relative_to(root).as_posix()
                    errors.append(f"{rel}:{line_no}: broken Markdown link '{target}'")
    return errors


def load_and_validate_yaml(reference_root: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        import jsonschema  # type: ignore
        import yaml  # type: ignore
    except ImportError:
        return {}, ["PyYAML and jsonschema are required; install their latest stable releases"]

    resource: dict = {}
    contracts = (
        (".scaffold/domain-specification.yaml", "schemas/domain-specification.schema.json"),
        (".scaffold/resource-implementation.yaml", "schemas/resource-implementation.schema.json"),
    )
    for data_rel, schema_rel in contracts:
        data_path = reference_root / data_rel
        schema_path = SCAFFOLD_ROOT / schema_rel
        if not data_path.is_file():
            errors.append(f"missing contract: {data_rel}")
            continue
        try:
            data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(data, schema)
            if data_rel.endswith("resource-implementation.yaml"):
                resource = data
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            errors.append(f"{data_rel}: cannot load contract: {exc}")
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
            errors.append(f"{data_rel}: schema violation at {location}: {exc.message}")
    return resource, errors


def _sentinel_errors(reference_root: Path, sentinels: tuple[tuple[str, str], ...], label: str) -> list[str]:
    errors: list[str] = []
    for rel, expected in sentinels:
        path = reference_root / rel
        if not path.is_file():
            errors.append(f"{label}: missing sentinel file: {rel}")
        elif expected not in path.read_text(encoding="utf-8"):
            errors.append(f"{label}: {rel}: missing feature sentinel '{expected}'")
    return errors


def _condition_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _condition_matches(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and set(actual) == set(expected)
    return actual == expected


def _condition_value(resource: dict, key: str) -> object:
    return resource.get(key)


def _strict_lane_errors(resource: dict) -> list[str]:
    lanes = resource.get("hostingLanes")
    if not isinstance(lanes, list):
        return []

    defaults = resource.get("hostingLaneDefaults")
    deploy_targets = resource.get("deployTargets")
    errors: list[str] = []
    for declared_lane in lanes:
        lane = "NonAzure" if declared_lane == "Portable" else declared_lane
        default_key = (
            lane
            if isinstance(defaults, dict) and lane in defaults
            else declared_lane
        )
        if not isinstance(defaults, dict) or not isinstance(defaults.get(default_key), dict):
            errors.append(f"lane {declared_lane}: hostingLaneDefaults.{default_key} is required")
            continue
        actual = defaults[default_key]
        expected = STRICT_LANE_DEFAULTS.get(lane)
        if expected is None:
            deployment_target = actual.get("deploymentTarget")
            if isinstance(deploy_targets, list) and deployment_target not in deploy_targets:
                errors.append(
                    f"lane {declared_lane}: deploymentTarget {deployment_target!r} must appear in deployTargets"
                )
            continue
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                errors.append(
                    f"strict lane {lane}: hostingLaneDefaults.{default_key}.{key} must be {expected_value!r}"
                )
        deployment_target = actual.get("deploymentTarget")
        if isinstance(deploy_targets, list) and deployment_target not in deploy_targets:
            errors.append(
                f"strict lane {lane}: deploymentTarget {deployment_target!r} must appear in deployTargets"
            )
    return errors


def check_declared_evidence(reference_root: Path, resource: dict) -> list[str]:
    """Declared-vs-wired agreement: every capability the reference declares must show its evidence."""
    errors: list[str] = []
    if resource.get("includeNotifications") is False and resource.get("notifications"):
        errors.append(".scaffold/resource-implementation.yaml: disabled notifications must not define notification entries")
    errors.extend(_strict_lane_errors(resource))

    errors.extend(_sentinel_errors(reference_root, ALWAYS_SENTINELS, "always"))
    for rel in ALWAYS_PATHS:
        if not (reference_root / rel).exists():
            errors.append(f"always: missing reference proof path: {rel}")

    for conditions, sentinels, paths in CONDITIONAL_EVIDENCE:
        matched = next(
            (
                cond for cond in conditions
                if all(
                    _condition_matches(_condition_value(resource, key), expected)
                    for key, expected in cond.items()
                )
            ),
            None,
        )
        if matched is None:
            continue
        label = ", ".join(f"{k}={v}" for k, v in matched.items())
        errors.extend(_sentinel_errors(reference_root, sentinels, label))
        for rel in paths:
            if not (reference_root / rel).exists():
                errors.append(f"{label}: missing declared-capability path: {rel}")
    return errors


def proof_paths(proof_map: Path) -> list[str]:
    paths: list[str] = []
    for span in CODE_SPAN_RE.findall(proof_map.read_text(encoding="utf-8")):
        for part in re.split(r",\s+|\s+\+\s+", span):
            candidate = part.strip().rstrip(".;:")
            if candidate.startswith(PROOF_ROOTS):
                paths.append(candidate)
    return paths


def check_proof_map(reference_root: Path) -> list[str]:
    proof_map = SCAFFOLD_ROOT / "support" / "taskflow-proof-map.md"
    errors: list[str] = []
    if not proof_map.is_file():
        return ["support/taskflow-proof-map.md is missing"]
    for rel in proof_paths(proof_map):
        if "*" in rel:
            if not list(reference_root.glob(rel)):
                errors.append(f"proof map glob matches nothing: {rel}")
        elif not (reference_root / rel).exists():
            errors.append(f"proof map path does not exist: {rel}")
    return errors


def check_action_refs(reference_root: Path) -> list[str]:
    errors: list[str] = []
    workflows = reference_root / ".github" / "workflows"
    for path in sorted(workflows.glob("*.y*ml")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = ACTION_REF_RE.search(line)
            if not match or match.group(1).startswith("./"):
                continue
            if not SHA_REF_RE.fullmatch(match.group(2)):
                rel = path.relative_to(reference_root).as_posix()
                errors.append(
                    f"{rel}:{line_no}: action '{match.group(1)}' must use an immutable 40-character SHA"
                )
    return errors


DEPENDABOT_REL = ".github/dependabot.yml"
DEPENDABOT_ECOSYSTEM_RE = re.compile(r"package-ecosystem:\s*[\"']?([A-Za-z-]+)[\"']?")
DEPENDABOT_DIRECTORY_RE = re.compile(r"directory:\s*[\"']?([^\s\"']+)[\"']?")
NUGET_FEED_RE = re.compile(r'<add key="[^"]+" value="(https?://[^"]+)"')


def check_dependabot(reference_root: Path) -> list[str]:
    """Dormant guard: a Dependabot opt-in must be configured so its update jobs and PRs can pass."""
    path = reference_root / DEPENDABOT_REL
    if not path.is_file():
        return []
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    entries: list[tuple[str, str]] = []
    ecosystem: str | None = None
    for line in text.splitlines():
        eco_match = DEPENDABOT_ECOSYSTEM_RE.search(line)
        if eco_match:
            ecosystem = eco_match.group(1)
            continue
        dir_match = DEPENDABOT_DIRECTORY_RE.search(line)
        if dir_match and ecosystem:
            entries.append((ecosystem, dir_match.group(1)))
            ecosystem = None

    for eco, directory in entries:
        root = reference_root / directory.lstrip("/")
        if eco == "npm" and not (root / "package.json").is_file():
            errors.append(f"{DEPENDABOT_REL}: npm directory '{directory}' has no package.json")
        if eco == "nuget" and not (
            list(root.glob("*.csproj")) or list(root.glob("*.sln*"))
            or (root / "Directory.Packages.props").is_file()
        ):
            errors.append(f"{DEPENDABOT_REL}: nuget directory '{directory}' has no project or packages file")

    nuget_config = reference_root / "nuget.config"
    private_feed = nuget_config.is_file() and any(
        "nuget.org" not in feed for feed in NUGET_FEED_RE.findall(nuget_config.read_text(encoding="utf-8"))
    )
    if private_feed and any(eco == "nuget" for eco, _ in entries) and "registries:" not in text:
        errors.append(
            f"{DEPENDABOT_REL}: nuget ecosystem with a private feed in nuget.config requires a "
            "registries block backed by a Dependabot secret"
        )
    return errors


def check_scaffold_model_names(reference_root: Path) -> list[str]:
    """Phase 1/2 artifacts record <latest-stable>, not a copied model name (skills/ai-integration.md)."""
    errors: list[str] = []
    for path in sorted((reference_root / ".scaffold").glob("*.yaml")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = CONCRETE_MODEL_PATTERN.search(line)
            if match:
                rel = path.relative_to(reference_root).as_posix()
                errors.append(f"{rel}:{line_no}: concrete model name '{match.group(0)}' - use <latest-stable>")
    return errors


def validate_reference(reference_root: Path) -> list[str]:
    if not reference_root.is_dir():
        return [f"reference root is not a directory: {reference_root}"]
    resource, errors = load_and_validate_yaml(reference_root)
    errors.extend(check_markdown_links(reference_root))
    errors.extend(check_proof_map(reference_root))
    errors.extend(check_declared_evidence(reference_root, resource))
    errors.extend(check_action_refs(reference_root))
    errors.extend(check_dependabot(reference_root))
    errors.extend(check_scaffold_model_names(reference_root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TaskFlow against the current scaffold checkout.")
    parser.add_argument("--reference-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.reference_root.resolve()
    errors = validate_reference(root)
    if errors:
        for error in errors:
            print(f"[fail] {error}")
        print(f"\n[fail] reference validation found {len(errors)} issue(s)")
        return 1
    print(f"[ok] reference contracts, links, proof paths, declared-capability evidence, action refs, dependabot config, and model-name placeholders match {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
