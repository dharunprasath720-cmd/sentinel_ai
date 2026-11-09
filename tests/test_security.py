import jwt
import pytest

from sentinel.security import (AuthError, Forbidden, create_token, decode_token, hash_password,
                               require_role, verify_password)

SECRET = "unit-test-secret-that-is-at-least-32-bytes-long"


class U:
    id, username, role, business_id = 7, "ana", "analyst", "biz1"


def test_password_hash_roundtrip_and_not_plaintext():
    h = hash_password("correct horse battery")
    assert "correct horse" not in h and h.startswith("$argon2")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", "not-a-hash")  # malformed hash is a failure, not a crash


def test_token_roundtrip_claims():
    claims = decode_token(create_token(U, SECRET), SECRET)
    # PyJWT requires `sub` to be a string
    assert (claims["sub"], claims["username"], claims["role"], claims["business_id"]) == \
        ("7", "ana", "analyst", "biz1")


def test_expired_token_rejected():
    with pytest.raises(AuthError):
        decode_token(create_token(U, SECRET, ttl_minutes=-1), SECRET)


def test_tampered_and_wrong_secret_tokens_rejected():
    good = create_token(U, SECRET)
    head, body, sig = good.split(".")
    with pytest.raises(AuthError):
        decode_token(f"{head}.{body}x.{sig}", SECRET)
    with pytest.raises(AuthError):
        decode_token(good, "a-different-secret-that-is-also-32-bytes-long")
    with pytest.raises(AuthError):
        decode_token("garbage", SECRET)


def test_unsigned_alg_none_token_rejected():
    forged = jwt.encode({"sub": 1, "role": "admin", "business_id": "biz1"}, key="", algorithm="none")
    with pytest.raises(AuthError):
        decode_token(forged, SECRET)


def test_require_role():
    require_role("analyst", {"analyst", "admin"})
    with pytest.raises(Forbidden):
        require_role("viewer", {"analyst", "admin"})
