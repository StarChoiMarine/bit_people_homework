import argparse
import json
import os
import secrets
import string
from pathlib import Path

from app.core.seed import SEED_ACCOUNTS


PASSWORD_LENGTH = 24
SPECIAL_CHARACTERS = "!@#$%&*+-_"


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + SPECIAL_CHARACTERS
    required_characters = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(SPECIAL_CHARACTERS),
    ]
    remaining_characters = [
        secrets.choice(alphabet)
        for _ in range(PASSWORD_LENGTH - len(required_characters))
    ]
    characters = required_characters + remaining_characters
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def write_credentials(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    credentials = {
        account["login_id"]: generate_password()
        for account in SEED_ACCOUNTS
    }
    file_descriptor = os.open(
        output_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as output_file:
        json.dump(credentials, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git에 포함하지 않을 시드 계정 비밀번호 파일을 생성합니다."
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        write_credentials(args.output)
    except FileExistsError:
        raise SystemExit(
            "출력 파일이 이미 존재합니다. 기존 파일을 보존하기 위해 중단했습니다."
        )
    print(f"자격증명 파일을 생성했습니다: {args.output}")


if __name__ == "__main__":
    main()
