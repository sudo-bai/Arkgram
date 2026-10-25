import contextlib
import html
import os
import subprocess
from pathlib import Path
from sys import argv

from pyrogram import Client
from pyrogram.types import InputMediaDocument, InputMediaPhoto

api_id = os.environ.get("APP_ID")
api_hash = os.environ.get("APP_HASH")
artifacts_path = Path("artifacts")
test_version = argv[3] == "test" if len(argv) > 2 else None
metadata_chat_id = argv[4] if len(argv) > 3 else None

def find_apk(abi: str) -> Path | None:
    return next((apk for apk in artifacts_path.rglob("*.apk") if abi in apk.name), None)

def get_commit_info():
    commit_id_raw = os.environ.get("COMMIT_ID") or "unknown"
    commit_id = commit_id_raw[:7]
    commit_url = os.environ.get("COMMIT_URL") or "https://github.com/sudo-bai/Arkgram/commits"
    commit_message = os.environ.get("COMMIT_MESSAGE") or "unknown"
    return commit_id, commit_url, commit_message

def get_app_version_name() -> str:
    version = os.environ.get("APP_VERSION_NAME")
    if version:
        return version.strip()

    properties = Path("gradle.properties")
    for line in properties.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "APP_VERSION_NAME":
            return value.strip()

    raise RuntimeError("APP_VERSION_NAME is missing from gradle.properties")


def render_cover() -> Path:
    commit_id, _, _ = get_commit_info()
    version = get_app_version_name()
    output = artifacts_path / f"Arkgram-v{version}-{commit_id}-cover.png"
    subprocess.run(
        [
            os.environ.get("NODE_BIN", "node"),
            "Tools/cover-renderer/render-cover.mjs",
            "--version",
            version,
            "--detail",
            commit_id,
            "--output",
            str(output),
        ],
        check=True,
    )
    return output


def get_caption() -> str:
    commit_id, commit_url, commit_message = get_commit_info()
    pre = "Test version." if test_version else "Release version."
    caption = f"{pre}\n\n"
    caption += f"Commit Message:\n<blockquote expandable>{html.escape(commit_message)}</blockquote>\n\n"
    caption += f"See commit details [{commit_id}]({commit_url})"
    return caption

def get_document() -> list:
    documents = []
    abis = ["arm64-v8a", "universal"]
    for abi in abis:
        if apk := find_apk(abi):
            documents.append(
                InputMediaDocument(
                    media = str(apk),
                )
            )
    if not documents:
        raise FileNotFoundError("No APK artifacts found")

    documents.insert(
        0,
        InputMediaPhoto(
            media = str(render_cover()),
        ),
    )
    base_caption = get_caption()
    if base_caption and len(base_caption) > 1024:
        base_caption = base_caption[:1020] + "..."
    documents[0].caption = base_caption
    return documents

def get_metadata():
    commit_id = "<code>" + (os.environ.get("COMMIT_ID") or "unknown")[:7] + "</code>"
    commit_message = "<code>" + html.escape(os.environ.get("COMMIT_MESSAGE") or "unknown") + "</code>"
    build_timestamp = "<code>" + (os.environ.get("BUILD_TIMESTAMP") or "-1") + "</code>"
    return build_timestamp + " " + commit_id + "\n" + commit_message

def retry(func):
    async def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                print(e)
                if attempt == 2:
                    raise
    return wrapper

@retry
async def send_to_channel(client: "Client", cid: str):
    with contextlib.suppress(ValueError):
        cid = int(cid)
    documents = get_document()
    print("Uploading to Telegram:", flush=True)
    for document in documents:
        print(f"- {document.media}", flush=True)
    await client.send_media_group(
        cid,
        media = documents,
    )

@retry
async def send_metadata(client: "Client", cid: str):
    with contextlib.suppress(ValueError):
        cid = int(cid)
    await client.send_message(
        chat_id = cid,
        text = get_metadata(),
    )

def get_client(bot_token: str):
    return Client(
        "helper_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
    )

async def main():
    bot_token = argv[1]
    chat_id = argv[2]
    client = get_client(bot_token)
    await client.start()
    await send_to_channel(client, chat_id)
    if metadata_chat_id:
        await send_metadata(client, metadata_chat_id)
    await client.log_out()

if __name__ == "__main__":
    from asyncio import run
    run(main())
