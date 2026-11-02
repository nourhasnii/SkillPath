import argparse
import getpass
import sqlite3

from .auth import EMAIL_PATTERN, PASSWORD_HASHER, validate_new_password
from .auth_store import create_admin


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SkillPath administrator account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    arguments = parser.parse_args()
    email = arguments.email.strip().lower()
    full_name = " ".join(arguments.name.split())
    if not EMAIL_PATTERN.fullmatch(email):
        parser.error("Enter a valid email address.")
    if not 2 <= len(full_name) <= 120:
        parser.error("The admin name must contain 2 to 120 characters.")
    password = getpass.getpass("Administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Password confirmation does not match.")
    try:
        validate_new_password(password)
    except ValueError as error:
        parser.error(str(error))
    try:
        account = create_admin(email, full_name, PASSWORD_HASHER.hash(password))
    except sqlite3.IntegrityError:
        parser.error("This email already has an account.")
    print(f"Administrator account created: {account.email}")


if __name__ == "__main__":
    main()
