"""Password hashing for story 1.1 (AC3: credentials are never stored in plain text).

Uses scrypt from the Python standard library, so no extra dependency is needed.
The stored format is::

    scrypt$<n>$<r>$<p>$<salt-hex>$<hash-hex>

Keeping the algorithm name and parameters in the string means the scheme can be
upgraded later (e.g. to argon2) while old hashes keep verifying.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "scrypt"
# CPU/memory cost parameters. These are moderate values suitable for a web login; raise `n`
# (must be a power of two) if hardware allows.
_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Return a self-describing hash string for ``password``.

    ``salt`` is only overridable for generating deterministic seed data; normal callers
    should let a fresh random salt be generated.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LEN)
    return f"{_ALGORITHM}${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time check of ``password`` against a hash produced by :func:`hash_password`."""
    try:
        algorithm, n, r, p, salt_hex, digest_hex = stored_hash.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)
