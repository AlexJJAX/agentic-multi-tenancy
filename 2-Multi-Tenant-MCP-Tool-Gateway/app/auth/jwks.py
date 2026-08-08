"""RSA key generation and JSON Web Key publication."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def ensure_rsa_keypair(private_path: Path, public_path: Path, *, generate: bool) -> None:
    """Create a stable development RSA keypair only when it is absent."""

    private_path.parent.mkdir(parents=True, exist_ok=True)
    if private_path.exists():
        private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
        if not public_path.exists():
            public_path.write_bytes(
                private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
        return
    if not generate:
        raise RuntimeError(f"Missing signing key: {private_path}")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(private_path, 0o600)
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def key_id(public_pem: bytes) -> str:
    """Derive a stable, non-secret key identifier from a public key."""

    public_key = serialization.load_pem_public_key(public_pem)
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:16]


def public_jwk(public_pem: bytes) -> dict[str, Any]:
    """Convert an RSA public key to a signing JWK."""

    public_key = serialization.load_pem_public_key(public_pem)
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise TypeError("Expected RSA public key")
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id(public_pem),
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }
