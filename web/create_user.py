"""Creates an account from the command line, e.g. when sign-up is closed (PDD_ALLOW_SIGNUP=false):

    .venv/bin/python -m web.create_user someone@company.com
    docker compose exec app python -m web.create_user someone@company.com   (on the server)
"""
import getpass
import sys
from dotenv import load_dotenv
from sqlmodel import select

from web.auth import MIN_PASSWORD, Credentials, hasher
from web.config import Settings
from web.db import User, make_engine, session


def main() -> None:
    load_dotenv()
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    email = Credentials(email=sys.argv[1], password="").email
    password = getpass.getpass(f"Password for {email}: ")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"The password needs at least {MIN_PASSWORD} characters.")
    if password != getpass.getpass("Repeat it: "):
        sys.exit("The passwords don't match.")
    with session(make_engine(Settings().database_url)) as db:
        user = db.exec(select(User).where(User.email == email)).first()
        if user:
            user.password_hash = hasher.hash(password)
            user.session_version = (user.session_version or 0) + 1  # logs out the account's sessions
            print(f"Password changed for {email}.")
        else:
            user = User(email=email, password_hash=hasher.hash(password))
            print(f"Account created for {email}.")
        db.add(user)
        db.commit()


if __name__ == "__main__":
    main()
