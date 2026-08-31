"""
password.py

Работа с паролями SA_03.

Использует Argon2id для:
    - создания password hash;
    - проверки пароля относительно hash.

Пароли в открытом виде нигде не сохраняются.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


# ==========================================================
# Password hasher
# ==========================================================

_password_hasher = PasswordHasher()


# ==========================================================
# Hash
# ==========================================================

def hash_password(password: str) -> str:
    """
    Создать Argon2id hash для пароля.
    """

    return _password_hasher.hash(
        password
    )


# ==========================================================
# Verify
# ==========================================================

def verify_password(
    password: str,
    password_hash: str
) -> bool:
    """
    Проверить пароль относительно Argon2id hash.

    Возвращает:
        True  — пароль правильный.
        False — пароль неправильный.
    """

    try:

        return _password_hasher.verify(
            password_hash,
            password
        )

    except VerifyMismatchError:

        return False