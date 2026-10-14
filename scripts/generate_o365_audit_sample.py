#!/usr/bin/env python3
"""Generate Microsoft 365 unified audit log sample data (JSON lines)."""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

ORG_ID = "a3f2c8d1-9e4b-4a7c-b6d0-1f2e3d4c5b6a"
TENANT = "contoso.onmicrosoft.com"
TARGET_BYTES = 50 * 1024 * 1024

USERS = [
    ("michael.rodriguez", "Michael Rodriguez"),
    ("jennifer.patel", "Jennifer Patel"),
    ("david.kim", "David Kim"),
    ("emily.watson", "Emily Watson"),
    ("james.okonkwo", "James Okonkwo"),
    ("lisa.martinez", "Lisa Martinez"),
    ("robert.singh", "Robert Singh"),
    ("amanda.fischer", "Amanda Fischer"),
    ("thomas.nguyen", "Thomas Nguyen"),
    ("sarah.chen", "Sarah Chen"),
]

LOCATIONS = [
    {
        "city": "Seattle",
        "state": "Washington",
        "country": "US",
        "countryOrRegion": "US",
        "latitude": 47.6062,
        "longitude": -122.3321,
        "ip_prefix": "52.112",
    },
    {
        "city": "Chicago",
        "state": "Illinois",
        "country": "US",
        "countryOrRegion": "US",
        "latitude": 41.8781,
        "longitude": -87.6298,
        "ip_prefix": "40.77",
    },
    {
        "city": "Austin",
        "state": "Texas",
        "country": "US",
        "countryOrRegion": "US",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "ip_prefix": "13.89",
    },
    {
        "city": "London",
        "state": "England",
        "country": "GB",
        "countryOrRegion": "GB",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "ip_prefix": "51.132",
    },
    {
        "city": "Frankfurt",
        "state": "Hesse",
        "country": "DE",
        "countryOrRegion": "DE",
        "latitude": 50.1109,
        "longitude": 8.6821,
        "ip_prefix": "52.58",
    },
    {
        "city": "Sydney",
        "state": "New South Wales",
        "country": "AU",
        "countryOrRegion": "AU",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "ip_prefix": "20.70",
    },
    {
        "city": "Toronto",
        "state": "Ontario",
        "country": "CA",
        "countryOrRegion": "CA",
        "latitude": 43.6532,
        "longitude": -79.3832,
        "ip_prefix": "40.84",
    },
    {
        "city": "Denver",
        "state": "Colorado",
        "country": "US",
        "countryOrRegion": "US",
        "latitude": 39.7392,
        "longitude": -104.9903,
        "ip_prefix": "104.42",
    },
]

LOGIN_OPS = [
    "UserLoggedIn",
    "UserLoginFailed",
    "UserLoggedIn",
    "UserLoggedIn",
]
OTHER_OPS = [
    "MailItemsAccessed",
    "FileAccessed",
    "FileDownloaded",
    "SharePointFileOperation",
    "TeamsMessageSent",
    "Add member to group.",
    "Update user.",
    "Change user license.",
]
WORKLOADS = {
    "UserLoggedIn": "AzureActiveDirectory",
    "UserLoginFailed": "AzureActiveDirectory",
    "UserLoggedIn": "AzureActiveDirectory",
    "MailItemsAccessed": "Exchange",
    "FileAccessed": "SharePoint",
    "FileDownloaded": "SharePoint",
    "SharePointFileOperation": "SharePoint",
    "TeamsMessageSent": "MicrosoftTeams",
    "Add member to group.": "AzureActiveDirectory",
    "Update user.": "AzureActiveDirectory",
    "Change user license.": "AzureActiveDirectory",
}
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Dalvik/2.1.0 (Linux; U; Android 14; SM-S918B Build/UP1A.231005.007)",
]

# Impossible travel: NYC -> Tokyo in 22 minutes (~10,850 km, >29,000 km/h required)
IMPOSSIBLE_TRAVEL = [
    {
        "user": "sarah.chen",
        "display": "Sarah Chen",
        "when": datetime(2026, 5, 15, 14, 12, 33, tzinfo=timezone.utc),
        "operation": "UserLoggedIn",
        "client_ip": "203.0.113.41",
        "geo": {
            "city": "New York",
            "state": "New York",
            "country": "US",
            "countryOrRegion": "US",
            "latitude": 40.7128,
            "longitude": -74.006,
        },
        "result": "Success",
        "request_type": "OAuth2:Authorize",
        "session_id": "8f3a2c1d-9e4b-4a7c-b6d0-1f2e3d4c5b6a",
    },
    {
        "user": "sarah.chen",
        "display": "Sarah Chen",
        "when": datetime(2026, 5, 15, 14, 34, 18, tzinfo=timezone.utc),
        "operation": "UserLoggedIn",
        "client_ip": "198.51.100.88",
        "geo": {
            "city": "Tokyo",
            "state": "Tokyo",
            "country": "JP",
            "countryOrRegion": "JP",
            "latitude": 35.6762,
            "longitude": 139.6503,
        },
        "result": "Success",
        "request_type": "OAuth2:Token",
        "session_id": "7e2b1a0c-8d3f-4e5a-9b8c-7d6e5f4a3b2c",
    },
]


def _ip_for_location(loc: dict) -> str:
    prefix = loc["ip_prefix"]
    return f"{prefix}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def _format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def build_login_event(
    *,
    user_alias: str,
    display_name: str,
    when: datetime,
    operation: str,
    client_ip: str,
    geo: dict,
    result_status: str,
    request_type: str = "OAuth2:Authorize",
    session_id: str | None = None,
    application_id: str = "00000003-0000-0ff1-ce00-000000000000",
) -> dict:
    upn = f"{user_alias}@{TENANT}"
    user_key = f"i:0#.f|membership|{upn}"
    event_id = str(uuid.uuid4())
    session_id = session_id or str(uuid.uuid4())

    extended = [
        {"Name": "ResultStatusDetail", "Value": "Success" if result_status == "Success" else "Failed"},
        {"Name": "UserAgent", "Value": random.choice(USER_AGENTS)},
        {"Name": "RequestType", "Value": request_type},
        {"Name": "SessionId", "Value": session_id},
    ]

    device_props = [
        {"Name": "OS", "Value": random.choice(["Windows10", "MacOs", "iOS", "Android"])},
        {"Name": "BrowserType", "Value": random.choice(["Chrome", "Edge", "Safari", "Firefox"])},
        {"Name": "IsCompliant", "Value": random.choice(["True", "False"])},
        {"Name": "IsCompliantAndManaged", "Value": random.choice(["True", "False"])},
    ]

    return {
        "CreationTime": _format_time(when),
        "Id": event_id,
        "Operation": operation,
        "OrganizationId": ORG_ID,
        "RecordType": 15,
        "ResultStatus": result_status,
        "UserKey": user_key,
        "UserType": 0,
        "Version": 1,
        "Workload": "AzureActiveDirectory",
        "ClientIP": client_ip,
        "ActorIpAddress": client_ip,
        "UserId": upn,
        "ObjectId": upn,
        "AzureActiveDirectoryEventType": 1,
        "ApplicationId": application_id,
        "Actor": [
            {"ID": upn, "Type": 5},
            {"ID": display_name, "Type": 0},
        ],
        "Target": [{"ID": upn, "Type": 5}],
        "ClientLocation": {
            "City": geo["city"],
            "State": geo["state"],
            "CountryOrRegion": geo["countryOrRegion"],
        },
        "GeoLocation": {
            "city": geo["city"],
            "state": geo["state"],
            "country": geo["country"],
            "countryOrRegion": geo["countryOrRegion"],
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
        },
        "ExtendedProperties": extended,
        "DeviceProperties": device_props,
        "AuthenticationType": random.choice(
            ["SingleFactorAuthentication", "MultifactorAuthentication", "Previously satisfied"]
        ),
        "LogonType": random.choice([0, 1, 2]),
        "IsManagedDevice": random.choice([True, False]),
        "IsInteractive": True,
    }


def build_other_event(
    *,
    user_alias: str,
    display_name: str,
    when: datetime,
    operation: str,
) -> dict:
    upn = f"{user_alias}@{TENANT}"
    loc = random.choice(LOCATIONS)
    client_ip = _ip_for_location(loc)
    workload = WORKLOADS.get(operation, "Exchange")

    return {
        "CreationTime": _format_time(when),
        "Id": str(uuid.uuid4()),
        "Operation": operation,
        "OrganizationId": ORG_ID,
        "RecordType": random.choice([6, 14, 36, 54]),
        "ResultStatus": random.choice(["Success", "Success", "Success", "PartialSuccess"]),
        "UserKey": f"i:0#.f|membership|{upn}",
        "UserType": 0,
        "Version": 1,
        "Workload": workload,
        "ClientIP": client_ip,
        "ActorIpAddress": client_ip,
        "UserId": upn,
        "ObjectId": upn,
        "Actor": [{"ID": upn, "Type": 5}, {"ID": display_name, "Type": 0}],
        "ClientLocation": {
            "City": loc["city"],
            "State": loc["state"],
            "CountryOrRegion": loc["countryOrRegion"],
        },
        "GeoLocation": {
            "city": loc["city"],
            "state": loc["state"],
            "country": loc["country"],
            "countryOrRegion": loc["countryOrRegion"],
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
        },
        "ExtendedProperties": [
            {"Name": "UserAgent", "Value": random.choice(USER_AGENTS)},
        ],
    }


def generate(output_path: str, target_bytes: int) -> int:
    rng = random.Random(42)
    start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 18, 0, 0, 0, tzinfo=timezone.utc)
    span_seconds = int((end - start).total_seconds())

    count = 0
    with open(output_path, "w", encoding="utf-8") as out:
        # Seed impossible-travel pair early so detectors can find it in any slice
        for spec in IMPOSSIBLE_TRAVEL:
            line = json.dumps(
                build_login_event(
                    user_alias=spec["user"],
                    display_name=spec["display"],
                    when=spec["when"],
                    operation=spec["operation"],
                    client_ip=spec["client_ip"],
                    geo=spec["geo"],
                    result_status=spec["result"],
                    request_type=spec["request_type"],
                    session_id=spec.get("session_id"),
                ),
                separators=(",", ":"),
            )
            out.write(line + "\n")
            count += 1

        while out.tell() < target_bytes:
            user_alias, display = rng.choice(USERS)
            when = start + timedelta(seconds=rng.randint(0, span_seconds))

            # ~35% login events with full geo
            if rng.random() < 0.35:
                loc = rng.choice(LOCATIONS)
                operation = rng.choice(LOGIN_OPS)
                result = "Success" if operation != "UserLoginFailed" else "Failed"
                event = build_login_event(
                    user_alias=user_alias,
                    display_name=display,
                    when=when,
                    operation=operation,
                    client_ip=_ip_for_location(loc),
                    geo=loc,
                    result_status=result,
                )
            else:
                event = build_other_event(
                    user_alias=user_alias,
                    display_name=display,
                    when=when,
                    operation=rng.choice(OTHER_OPS),
                )

            out.write(json.dumps(event, separators=(",", ":")) + "\n")
            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate O365 audit JSONL sample data")
    parser.add_argument(
        "-o",
        "--output",
        default="sample-data/spot_o365_audit_sample.log",
        help="Output file path",
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=TARGET_BYTES,
        help="Target file size in bytes (default: 50MB)",
    )
    args = parser.parse_args()

    count = generate(args.output, args.bytes)
    import os

    size = os.path.getsize(args.output)
    print(f"Wrote {count:,} events to {args.output}")
    print(f"File size: {size:,} bytes ({size / (1024 * 1024):.2f} MiB)")


if __name__ == "__main__":
    main()
