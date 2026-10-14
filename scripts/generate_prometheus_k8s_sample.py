#!/usr/bin/env python3
"""Generate Prometheus text exposition sample data (high-cardinality K8s metrics)."""

from __future__ import annotations

import argparse
import os
import random
import time
from datetime import datetime, timedelta, timezone

TARGET_BYTES = 1000 * 1024 * 1024  # 1000 MiB

CLUSTER = "prod-us-east-1"
JOB_KUBELET = "kubelet"
JOB_CADVISOR = "cadvisor"
JOB_KSM = "kube-state-metrics"
JOB_APISERVER = "apiserver"

NAMESPACES = [
    "kube-system",
    "monitoring",
    "ingress-nginx",
    "cert-manager",
    "default",
    * [f"app-{i:03d}" for i in range(80)],
]

DEPLOYMENTS = [
    "api-gateway",
    "auth-service",
    "billing-worker",
    "cart-service",
    "catalog-api",
    "checkout-api",
    "inventory-sync",
    "notification-dispatcher",
    "order-processor",
    "payment-adapter",
    "recommendation-engine",
    "search-indexer",
    "session-store",
    "user-profile",
    "web-frontend",
]

CONTAINERS = ["app", "sidecar", "istio-proxy", "metrics-exporter"]

PHASES = ["Running", "Pending", "Succeeded", "Failed", "Unknown"]
HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
HTTP_STATUS = ["200", "201", "204", "301", "400", "401", "403", "404", "429", "500", "502", "503"]
HTTP_HANDLERS = [
    "/healthz",
    "/readyz",
    "/metrics",
    "/api/v1/users",
    "/api/v1/orders",
    "/api/v1/products",
    "/api/v2/search",
    "/api/v2/checkout",
    "/graphql",
    "/webhooks/stripe",
]

METRIC_HEADERS = [
    "# HELP container_cpu_usage_seconds_total Cumulative cpu time consumed per container in seconds.",
    "# TYPE container_cpu_usage_seconds_total counter",
    "# HELP container_memory_working_set_bytes Current working set in bytes.",
    "# TYPE container_memory_working_set_bytes gauge",
    "# HELP container_network_receive_bytes_total Cumulative count of bytes received.",
    "# TYPE container_network_receive_bytes_total counter",
    "# HELP container_network_transmit_bytes_total Cumulative count of bytes transmitted.",
    "# TYPE container_network_transmit_bytes_total counter",
    "# HELP kube_pod_container_status_restarts_total Number of restarts per container.",
    "# TYPE kube_pod_container_status_restarts_total counter",
    "# HELP kube_pod_status_phase The pods current phase.",
    "# TYPE kube_pod_status_phase gauge",
    "# HELP kube_deployment_status_replicas The number of replicas per deployment.",
    "# TYPE kube_deployment_status_replicas gauge",
    "# HELP apiserver_request_total Counter of apiserver requests broken out by verb, resource, scope, code.",
    "# TYPE apiserver_request_total counter",
    "# HELP grpc_server_handled_total Total number of RPCs completed on the server.",
    "# TYPE grpc_server_handled_total counter",
]


def _build_topology(rng: random.Random) -> list[dict]:
    """Pre-build high-cardinality pod/container label sets."""
    pods: list[dict] = []
    node_idx = 0
    for ns in NAMESPACES:
        for dep in DEPLOYMENTS:
            replicas = rng.randint(3, 12)
            for r in range(replicas):
                pod = f"{dep}-{rng.randint(100000, 999999):x}-{r:02d}"
                node = f"ip-10-{rng.randint(0, 255)}-{rng.randint(0, 255)}-{rng.randint(1, 254)}.ec2.internal"
                instance = f"10.{node_idx % 255}.{rng.randint(0, 255)}.{rng.randint(1, 254)}:10250"
                node_idx += 1
                uid = f"{rng.randint(0, 0xFFFFFFFF):08x}-{rng.randint(0, 0xFFFF):04x}"
                rs = f"{dep}-{rng.randint(10000000, 99999999)}"
                image = f"registry.example.com/{dep}@sha256:{rng.randint(0, 2**64 - 1):016x}"
                for container in CONTAINERS:
                    if container == "app" or rng.random() < 0.45:
                        pods.append(
                            {
                                "namespace": ns,
                                "pod": pod,
                                "container": container,
                                "deployment": dep,
                                "replicaset": rs,
                                "node": node,
                                "instance": instance,
                                "uid": uid,
                                "image": image,
                                "id": f"/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod{uid.replace('-', '_')}.slice/docker-{rng.randint(0, 2**64 - 1):012x}.scope",
                            }
                        )
    return pods


def _format_labels(labels: dict[str, str]) -> str:
    parts = [f'{k}="{v}"' for k, v in labels.items()]
    return "{" + ",".join(parts) + "}"


def _scrape_block(pods: list[dict], ts_ms: int, rng: random.Random) -> str:
    lines: list[str] = []
    lines.extend(METRIC_HEADERS)
    lines.append("")

    for p in pods:
        base = {
            "namespace": p["namespace"],
            "pod": p["pod"],
            "container": p["container"],
            "instance": p["instance"],
            "node": p["node"],
            "job": JOB_KUBELET,
            "cluster": CLUSTER,
        }
        cpu_labels = {
            **base,
            "id": p["id"],
            "image": p["image"],
            "name": f"k8s_{p['container']}_{p['pod']}_{p['namespace']}_{p['uid']}",
        }
        cpu_val = rng.uniform(10.0, 50000.0)
        mem_val = int(rng.uniform(1e6, 2e9))
        rx_val = int(rng.uniform(1e5, 1e11))
        tx_val = int(rng.uniform(1e5, 1e11))
        restarts = rng.randint(0, 25)

        lines.append(
            f"container_cpu_usage_seconds_total{_format_labels(cpu_labels)} {cpu_val:.6f} {ts_ms}"
        )
        lines.append(
            f"container_memory_working_set_bytes{_format_labels(base)} {mem_val} {ts_ms}"
        )
        lines.append(
            f"container_network_receive_bytes_total{_format_labels({**base, 'interface': 'eth0'})} {rx_val} {ts_ms}"
        )
        lines.append(
            f"container_network_transmit_bytes_total{_format_labels({**base, 'interface': 'eth0'})} {tx_val} {ts_ms}"
        )
        lines.append(
            f"kube_pod_container_status_restarts_total{_format_labels({'namespace': p['namespace'], 'pod': p['pod'], 'container': p['container'], 'uid': p['uid'], 'job': JOB_KSM, 'cluster': CLUSTER})} {restarts} {ts_ms}"
        )

        phase = rng.choice(PHASES)
        phase_labels = {
            "namespace": p["namespace"],
            "pod": p["pod"],
            "uid": p["uid"],
            "phase": phase,
            "job": JOB_KSM,
            "cluster": CLUSTER,
        }
        lines.append(f"kube_pod_status_phase{_format_labels(phase_labels)} {1 if phase == 'Running' else 0} {ts_ms}")

    # Deployment-level (lower frequency but still many series)
    seen_dep: set[tuple[str, str]] = set()
    for p in pods:
        key = (p["namespace"], p["deployment"])
        if key in seen_dep:
            continue
        seen_dep.add(key)
        dep_labels = {
            "namespace": p["namespace"],
            "deployment": p["deployment"],
            "job": JOB_KSM,
            "cluster": CLUSTER,
        }
        replicas = rng.randint(1, 20)
        lines.append(f"kube_deployment_status_replicas{_format_labels(dep_labels)} {replicas} {ts_ms}")

    # Apiserver + gRPC (per-pod high cardinality)
    sample = pods if len(pods) <= 400 else rng.sample(pods, 400)
    for p in sample:
        api_labels = {
            "verb": rng.choice(["GET", "LIST", "WATCH", "POST", "PATCH", "DELETE"]),
            "resource": rng.choice(["pods", "deployments", "services", "configmaps", "secrets", "nodes"]),
            "scope": rng.choice(["cluster", "namespace", "resource"]),
            "code": rng.choice(HTTP_STATUS),
            "job": JOB_APISERVER,
            "cluster": CLUSTER,
            "instance": "10.0.0.1:443",
        }
        lines.append(f"apiserver_request_total{_format_labels(api_labels)} {rng.randint(1, 500000)} {ts_ms}")

        grpc_labels = {
            "grpc_code": rng.choice(["OK", "Canceled", "Unknown", "DeadlineExceeded", "NotFound"]),
            "grpc_method": rng.choice(["Check", "List", "Watch", "Create", "Update"]),
            "grpc_service": rng.choice(
                ["grpc.health.v1.Health", "etcdserverpb.KV", "etcdserverpb.Watch"]
            ),
            "grpc_type": rng.choice(["unary", "server_stream", "client_stream"]),
            "namespace": p["namespace"],
            "pod": p["pod"],
            "job": "istio-proxy",
            "cluster": CLUSTER,
        }
        lines.append(f"grpc_server_handled_total{_format_labels(grpc_labels)} {rng.randint(0, 100000)} {ts_ms}")

        http_labels = {
            "method": rng.choice(HTTP_METHODS),
            "status": rng.choice(HTTP_STATUS),
            "handler": rng.choice(HTTP_HANDLERS),
            "namespace": p["namespace"],
            "pod": p["pod"],
            "container": p["container"],
            "job": "app",
            "cluster": CLUSTER,
        }
        lines.append(
            f"http_requests_total{_format_labels(http_labels)} {rng.randint(1, 2000000)} {ts_ms}"
        )

    return "\n".join(lines) + "\n"


def generate(output_path: str, target_bytes: int, seed: int = 42) -> int:
    rng = random.Random(seed)
    pods = _build_topology(rng)
    scrape_interval = timedelta(seconds=15)
    start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    scrapes = 0

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(output_path, "w", encoding="utf-8", buffering=1024 * 1024) as out:
        out.write(
            f"# Synthetic Prometheus exposition — kube-prometheus / kube-state-metrics style\n"
            f"# cluster={CLUSTER} generated_at={generated_at}\n"
        )

        while out.tell() < target_bytes:
            when = start + scrape_interval * scrapes
            ts_ms = int(when.timestamp() * 1000)
            out.write(_scrape_block(pods, ts_ms, rng))
            scrapes += 1

    return scrapes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Prometheus text exposition sample (K8s high-cardinality)"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="sample-data/spot_prometheus_k8s_sample.prom",
        help="Output file path",
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=TARGET_BYTES,
        help="Target file size in bytes (default: 1000 MiB)",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = parser.parse_args()

    t0 = time.perf_counter()
    scrapes = generate(args.output, args.bytes, seed=args.seed)
    elapsed = time.perf_counter() - t0
    size = os.path.getsize(args.output)
    print(f"Wrote {scrapes:,} scrape blocks to {args.output}")
    print(f"Topology: {len(NAMESPACES)} namespaces, {len(DEPLOYMENTS)} deployments/pod templates")
    print(f"File size: {size:,} bytes ({size / (1024 * 1024):.2f} MiB)")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
