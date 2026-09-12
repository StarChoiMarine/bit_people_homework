import base64
import hashlib
import hmac
import secrets


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_SIZE = 16
HASH_SIZE = 64


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_SIZE)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=HASH_SIZE,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_encode(salt)}${_encode(password_hash)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected_hash = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False

        actual_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_decode(expected_hash)),
        )
        return hmac.compare_digest(actual_hash, _decode(expected_hash))
    except (TypeError, ValueError):
        return False

