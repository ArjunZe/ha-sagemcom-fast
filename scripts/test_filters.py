"""Check Sagemcom device filter rules against sample device data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re


FILTER_FIELDS = (
    "id",
    "name",
    "user_friendly_name",
    "phys_address",
    "ip_address",
    "interface_type",
    "user_host_name",
    "host_name",
)


@dataclass
class SampleDevice:
    """Minimal device shape used by the integration filter."""

    id: str = ""
    name: str = ""
    user_friendly_name: str = ""
    phys_address: str = ""
    ip_address: str = ""
    interface_type: str = ""
    user_host_name: str = ""
    host_name: str = ""


def compile_rules(rules: str) -> list[re.Pattern]:
    """Compile newline-separated regex rules."""
    return [re.compile(rule.strip()) for rule in rules.splitlines() if rule.strip()]


def device_text(device: SampleDevice) -> str:
    """Return the text that regex rules will search."""
    return "\n".join(
        str(value)
        for field in FILTER_FIELDS
        if (value := getattr(device, field, None))
    )


def is_allowed(
    device: SampleDevice,
    include_rules: list[re.Pattern],
    exclude_rules: list[re.Pattern],
) -> bool:
    """Return whether a sample device passes the filter rules."""
    text = device_text(device)
    if include_rules and not any(rule.search(text) for rule in include_rules):
        return False
    return not any(rule.search(text) for rule in exclude_rules)


def main() -> None:
    """Run a sample filter check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", default="", help="Include regex rules, one per line")
    parser.add_argument("--exclude", default="", help="Exclude regex rules, one per line")
    parser.add_argument("--name", default="Jane-iPhone")
    parser.add_argument("--mac", default="AA:BB:CC:DD:EE:FF")
    parser.add_argument("--ip", default="192.168.1.42")
    parser.add_argument("--interface", default="wifi")
    parser.add_argument("--hostname", default="jane-iphone")
    args = parser.parse_args()

    device = SampleDevice(
        id=args.mac,
        name=args.name,
        user_friendly_name=args.name,
        phys_address=args.mac,
        ip_address=args.ip,
        interface_type=args.interface,
        user_host_name=args.hostname,
        host_name=args.hostname,
    )

    include_rules = compile_rules(args.include)
    exclude_rules = compile_rules(args.exclude)
    result = "allowed" if is_allowed(device, include_rules, exclude_rules) else "blocked"
    print(result)


if __name__ == "__main__":
    main()
