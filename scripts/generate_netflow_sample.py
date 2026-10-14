#!/usr/bin/env python3
"""Generate NetFlow v9-style flow records as JSON lines (~target byte size)."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone

TARGET_BYTES = 10 * 1024 * 1024

EXPORTERS = [f"netflow-exporter-{i:02d}.corp.example.com" for i in range(1, 13)]
EXPORTER_IPS = [f"10.255.{i}.{j}" for i in range(1, 5) for j in range(1, 20)]

PROTOCOLS = {
    1: ("icmp", "icmp"),
    6: ("tcp", "http"),
    17: ("udp", "dns"),
    47: ("gre", "gre"),
}

TCP_FLAGS = ["S", "SA", "A", "FA", "R", "PA", "SYN", "ACK", "FIN"]

APPLICATIONS = ["https", "dns", "ssh", "ntp", "ldap", "kerberos", "smtp", "unknown"]

DIRECTIONS = ["ingress", "egress", "internal", "external"]

ASNS = [64512, 64513, 15169, 8075, 16509, 13335, 20940, 32934]


def _host_pool(rng: random.Random, n: int = 4000) -> list[str]:
    hosts: list[str] = []
    for _ in range(n):
        hosts.append(f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}")
    for _ in range(n // 4):
        hosts.append(f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}")
    return hosts


def _public_ip(rng: random.Random) -> str:
    while True:
        a, b, c, d = (rng.randint(1, 223), rng.randint(0, 255), rng.randint(0, 255), rng.randint(1, 254))
        if a in (10, 127, 172) or (a == 172 and 16 <= b <= 31):
            continue
        return f"{a}.{b}.{c}.{d}"


def build_flow(rng: random.Random, hosts: list[str], when: datetime) -> dict:
    proto_id = rng.choices(list(PROTOCOLS.keys()), weights=[5, 55, 38, 2])[0]
    transport, app = PROTOCOLS[proto_id]
    src = rng.choice(hosts)
    dst = rng.choice(hosts) if rng.random() < 0.55 else _public_ip(rng)
    if src == dst:
        dst = _public_ip(rng)
    sport = rng.randint(1024, 65535)
    dport = rng.choice([22, 53, 80, 443, 8080, 8443, 3389, 5432, 123, 389, sport])
    packets = rng.randint(1, 5000)
    bytes_ = rng.randint(64, packets * 1400)
    duration_ms = rng.randint(1, 120_000)
    end = when
    start = when - timedelta(milliseconds=duration_ms)
    ingress = rng.randint(1, 128)
    egress = rng.randint(1, 128)
    exporter = rng.choice(EXPORTERS)
    exporter_ip = rng.choice(EXPORTER_IPS)
    direction = rng.choice(DIRECTIONS)
    tcp_flags = rng.choice(TCP_FLAGS) if proto_id == 6 else None

    flow_id = rng.randint(1, 2**31 - 1)
    flow_key = f"{src}-{sport}-{dst}-{dport}-{proto_id}"

    return {
        "type": "netflow.flow",
        "export": {
            "version": 9,
            "type": "netflow_v9",
            "host": exporter,
            "ip": exporter_ip,
            "timestamp": when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        },
        "flow": {
            "flowId": flow_id,
            "flowKey": flow_key,
            "sourceIPv4Address": src,
            "destinationIPv4Address": dst,
            "protocolIdentifier": proto_id,
            "sourceTransportPort": sport,
            "destinationTransportPort": dport,
            "packetDeltaCount": packets,
            "octetDeltaCount": bytes_,
            "flowStartMilliseconds": start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "flowEndMilliseconds": end.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "ingressInterface": ingress,
            "egressInterface": egress,
            "sourceAS": rng.choice(ASNS),
            "destinationAS": rng.choice(ASNS),
            "tcpControlBits": tcp_flags,
            "ipClassOfService": rng.randint(0, 63),
            "direction": direction,
            "applicationName": rng.choice(APPLICATIONS),
            "network.transport": transport,
        },
    }


def generate(output_path: str, target_bytes: int, seed: int = 42) -> int:
    rng = random.Random(seed)
    hosts = _host_pool(rng)
    start = datetime(2026, 5, 22, 8, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 22, 18, 0, 0, tzinfo=timezone.utc)
    span = int((end - start).total_seconds())

    count = 0
    with open(output_path, "w", encoding="utf-8") as out:
        while out.tell() < target_bytes:
            when = start + timedelta(seconds=rng.randint(0, span), microseconds=rng.randint(0, 999999))
            record = build_flow(rng, hosts, when)
            out.write(json.dumps(record, separators=(",", ":")) + "\n")
            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NetFlow v9 JSONL sample data")
    parser.add_argument(
        "-o",
        "--output",
        default="sample-data/spot_netflow_sample.log",
        help="Output file path",
    )
    parser.add_argument("--bytes", type=int, default=TARGET_BYTES, help="Target size in bytes")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    count = generate(args.output, args.bytes, seed=args.seed)
    import os

    size = os.path.getsize(args.output)
    print(f"Wrote {count:,} flow records to {args.output}")
    print(f"File size: {size:,} bytes ({size / (1024 * 1024):.2f} MiB)")


if __name__ == "__main__":
    main()
