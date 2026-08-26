from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # A malformed, empty, or truncated stored hash — for example a
        # placeholder value on an SSO-only row created via external_id —
        # must fail the same way a wrong password does. Letting this
        # propagate would produce a 500 instead of a 401, and that split
        # is itself a way to distinguish account states from the outside.
        return False
