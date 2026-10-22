"""DEGIRO source identities and ownership grammar."""

import re


def execution_comment(source_account: object, execution_id: object) -> str:
    return f"DEGIRO#{broker_identity(source_account)}:TRADE:{broker_identity(execution_id)}"


def broker_identity(value: object) -> str:
    if (isinstance(value, bool) or not isinstance(value, (int, str))
            or not re.fullmatch(r"[1-9][0-9]*", str(value))):
        raise RuntimeError("Invalid DEGIRO identity")
    return str(value)


def parse_legacy_identity(comment: object) -> tuple[str, str, str] | None:
    """Parse only the existing canonical grammar; do not infer ownership."""
    if not isinstance(comment, str):
        return None
    match = re.fullmatch(
        r"DEGIRO#([1-9][0-9]*):(TRADE|DIVIDEND|FEE|INTEREST|COMPENSATION):([1-9][0-9]*)",
        comment,
    )
    if match is None:
        return None
    return match[1], match[2], match[3]
