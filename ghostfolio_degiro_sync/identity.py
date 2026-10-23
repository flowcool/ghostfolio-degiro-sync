"""DEGIRO source identities and ownership grammar."""

import re


def execution_comment(source_account: object, execution_id: object) -> str:
    return versioned_comment(source_account, "TRADE", execution_id)


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


KIND_TYPES = {'TRADE': ('BUY', 'SELL'), 'DIVIDEND': ('DIVIDEND',), 'FEE': ('FEE',),
              'INTEREST': ('INTEREST',), 'COMPENSATION': ('INTEREST',)}


def parse_identity(comment: object, activity_type: object=None) -> tuple[str, str, str] | None:
    """Read legacy/v1 ownership without trimming or inventing a source identity."""
    if not isinstance(comment, str) or not comment.startswith('DEGIRO#'):
        return None
    if not comment.isascii() or len(comment) > 2000:
        raise RuntimeError('Malformed existing DEGIRO canonical identity')
    result: tuple[str, str, str] | None
    if comment.startswith('DEGIRO#v'):
        match = re.fullmatch(r'DEGIRO#v1#([1-9][0-9]*):(TRADE|DIVIDEND|FEE|INTEREST|COMPENSATION):([1-9][0-9]*)', comment)
        if match is None:
            raise RuntimeError('Malformed existing DEGIRO canonical identity')
        result = (match[1], match[2], match[3])
    else:
        result = parse_legacy_identity(comment)
        if result is None:
            raise RuntimeError('Malformed existing DEGIRO canonical identity')
    if activity_type is not None and activity_type not in KIND_TYPES[result[1]]:
        raise RuntimeError('DEGIRO identity kind conflicts with activity type')
    return result


def versioned_comment(source_account: object, kind: str, source_id: object) -> str:
    comment = f'DEGIRO#v1#{broker_identity(source_account)}:{kind}:{broker_identity(source_id)}'
    parse_identity(comment)
    return comment


def canonical_comment(comment: object, activity_type: object=None) -> str | None:
    """Canonical comparison spelling; never replace a stored comment."""
    key = parse_identity(comment, activity_type)
    return f'DEGIRO#{key[0]}:{key[1]}:{key[2]}' if key else None
