"""Story 1.1 AC3 - stored credentials are not held in plain text (unit tests, no database)."""

import pytest

from app.auth.passwords import hash_password, verify_password


@pytest.mark.story("1.1", ac=3)
def test_hash_does_not_contain_the_password():
    hashed = hash_password("Password123!")
    assert "Password123!" not in hashed
    assert hashed.startswith("scrypt$")


@pytest.mark.story("1.1", ac=3)
def test_same_password_hashes_differently_each_time():
    assert hash_password("Password123!") != hash_password("Password123!")


@pytest.mark.story("1.1", ac=3)
def test_verify_accepts_correct_and_rejects_wrong_password():
    hashed = hash_password("correct horse")
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong horse", hashed)


@pytest.mark.story("1.1", ac=3)
@pytest.mark.parametrize("garbage", ["", "plaintext", "md5$abc", "scrypt$x$y$z$notnhex$zz"])
def test_verify_rejects_malformed_hashes(garbage):
    assert not verify_password("anything", garbage)


@pytest.mark.story("1.1", ac=3)
def test_empty_password_cannot_be_hashed():
    with pytest.raises(ValueError):
        hash_password("")
