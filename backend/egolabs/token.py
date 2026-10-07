"""Print an API access token for an existing, active account, for scripts such as `make seed` (people
sign in with Google, so their accounts have no password). Run it with the API's settings (it signs with
JWT_SECRET and reads DATABASE_URL):

    python -m egolabs.token you@gmail.com
"""

import sys

from sqlalchemy import select

from egolabs.db import get_sessionmaker
from egolabs.models import User
from egolabs.security import create_access_token


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == argv[0].strip().lower()))
    if user is None or not user.is_active:
        print(f"No active account for {argv[0]}. Sign in with Google once to create it.", file=sys.stderr)
        return 1
    print(create_access_token(user.id)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
