"""
test_password.py

Тесты модуля api.password.
"""

from password import (
    hash_password,
    verify_password,
)


def test_password_hash():
    """Проверка создания Argon2id hash."""

    password = "TestPassword123!"

    password_hash = hash_password(
        password
    )

    assert password_hash.startswith(
        "$argon2id$"
    )

    assert password_hash != password


def test_password_verify_correct():
    """Правильный пароль должен пройти проверку."""

    password = "TestPassword123!"

    password_hash = hash_password(
        password
    )

    assert verify_password(
        password,
        password_hash
    ) is True


def test_password_verify_wrong():
    """Неправильный пароль не должен пройти проверку."""

    password = "TestPassword123!"

    password_hash = hash_password(
        password
    )

    assert verify_password(
        "WrongPassword",
        password_hash
    ) is False


def test_same_password_creates_different_hash():
    """
    Два hash одного пароля должны отличаться
    из-за случайной salt.
    """

    password = "TestPassword123!"

    hash1 = hash_password(
        password
    )

    hash2 = hash_password(
        password
    )

    assert hash1 != hash2

    assert verify_password(
        password,
        hash1
    ) is True

    assert verify_password(
        password,
        hash2
    ) is True