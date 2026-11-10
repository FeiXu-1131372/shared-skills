#!/usr/bin/env python3
"""Read-only verification of Switchboard release assets; downloads to scratch."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import struct
import subprocess
import sys
import tarfile
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh(*args):
    env = os.environ.copy()
    env.pop("GH_DEBUG", None)
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", env=env
    )
    if result.returncode:
        raise ValueError(f"GitHub CLI failed: {result.stderr.strip()}")
    return result.stdout


def signature_text(value):
    value = value.strip()
    if not value.startswith("untrusted comment:"):
        value = base64.b64decode(value, validate=True).decode("utf-8").strip()
    return "\n".join(value.splitlines())


def verify_signature(data, signature, public_packet):
    """Verify Minisign's payload and trusted-comment signatures, including ED prehash."""
    lines = signature_text(signature).splitlines()
    require(len(lines) == 4, "Invalid Minisign signature format")
    require(lines[2].startswith("trusted comment: "), "Missing trusted comment")
    packet = base64.b64decode(lines[1], validate=True)
    require(len(packet) == 74 and packet[:2] in (b"Ed", b"ED"), "Invalid signature packet")
    require(packet[2:10] == public_packet[2:10], "Updater signing key ID mismatch")
    key = Ed25519PublicKey.from_public_bytes(public_packet[10:])
    message = hashlib.blake2b(data, digest_size=64).digest() if packet[:2] == b"ED" else data
    try:
        key.verify(packet[10:], message)
        key.verify(base64.b64decode(lines[3], validate=True), packet[10:] + lines[2][17:].encode())
    except InvalidSignature as error:
        raise ValueError("Updater signature verification failed") from error


def verify_macos(archive_path, version, identifier):
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [m for m in archive.getmembers() if m.name.endswith("/Contents/Info.plist")]
        require(len(members) == 1, "Expected one macOS app Info.plist")
        info_member = members[0]
        info = plistlib.loads(archive.extractfile(info_member).read())
        require(info["CFBundleShortVersionString"] == version, "macOS app version mismatch")
        require(info["CFBundleIdentifier"] == identifier, "macOS bundle identifier mismatch")
        directory = info_member.name.removesuffix("Info.plist") + "MacOS/"
        executables = [info["CFBundleExecutable"]]
        if tuple(map(int, version.split("."))) >= (1, 4, 0):
            executables.append("switchboard-statusline")
        for name in executables:
            member = archive.getmember(directory + name)
            require(member.isfile() and member.mode & 0o111, f"Missing executable: {name}")
            header = archive.extractfile(member).read(1024)
            magic, count = struct.unpack(">II", header[:8])
            require(magic in (0xCAFEBABE, 0xCAFEBABF) and 1 < count < 10, f"Not universal: {name}")
            stride = 20 if magic == 0xCAFEBABE else 32
            architectures = {
                struct.unpack(">I", header[8 + i * stride:12 + i * stride])[0]
                for i in range(count)
            }
            require({0x01000007, 0x0100000C} <= architectures, f"Missing Intel/Apple Silicon: {name}")
            print(f"Verified universal macOS executable: {name}")


def verify_release(args):
    require(re.fullmatch(r"v\d+\.\d+\.\d+", args.tag), "Use a stable version tag such as v1.4.0")
    require(re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo), "Invalid repository owner/name")
    version = args.tag[1:]
    config = json.loads(args.config.read_text(encoding="utf-8"))
    # Listing also finds drafts, which GitHub's get-release-by-tag endpoint omits.
    pages = json.loads(gh("api", f"repos/{args.repo}/releases", "--paginate", "--slurp"))
    matches = [release for page in pages for release in page if release["tag_name"] == args.tag]
    require(len(matches) == 1, "Expected exactly one release for this tag; inspect missing/duplicate records")
    release = matches[0]
    require(args.allow_draft or not release["draft"], "Release is still a draft")
    require(not release["prerelease"], "Expected a stable release")
    assets = {asset["name"]: asset for asset in release["assets"]}
    required = {
        f"Claude.Switchboard_{version}_universal.dmg",
        f"Claude.Switchboard_{version}_x64-setup.exe",
        f"Claude.Switchboard_{version}_x64-setup.exe.sig",
        "Claude.Switchboard_universal.app.tar.gz",
        "Claude.Switchboard_universal.app.tar.gz.sig",
        "latest.json",
    }
    require(required <= assets.keys(), f"Missing assets: {sorted(required - assets.keys())}")
    for name in assets:
        require(name not in (".", "..") and not any(c in name for c in "/\\:"), "Unsafe asset filename")
    destination = args.download_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    gh("release", "download", args.tag, "--repo", args.repo, "--dir", str(destination), "--clobber")
    for name, asset in assets.items():
        data = (destination / name).read_bytes()
        require(asset["state"] == "uploaded" and len(data) == asset["size"] > 0, f"Asset size/state: {name}")
        if asset.get("digest"):
            require(asset["digest"] == "sha256:" + hashlib.sha256(data).hexdigest(), f"Asset digest: {name}")

    manifest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
    require(manifest["version"] == version, "Updater manifest version mismatch")
    expected = {"darwin-aarch64", "darwin-x86_64", "windows-x86_64"}
    require(expected <= manifest["platforms"].keys(), "Missing updater platform entries")
    key_text = base64.b64decode(config["plugins"]["updater"]["pubkey"], validate=True).decode()
    public_packet = base64.b64decode(key_text.splitlines()[1], validate=True)
    require(len(public_packet) == 42 and public_packet[:2] in (b"Ed", b"ED"), "Invalid updater public key")
    verified = set()
    for platform, entry in manifest["platforms"].items():
        require(entry["url"].startswith(f"https://github.com/{args.repo}/releases/download/{args.tag}/"),
                f"Updater URL points outside this release: {platform}")
        name = unquote(PurePosixPath(urlsplit(entry["url"]).path).name)
        require(name in assets and name + ".sig" in assets, f"Updater asset/signature missing: {platform}")
        signature = signature_text(entry["signature"])
        require(signature == signature_text((destination / (name + ".sig")).read_text(encoding="utf-8")),
                f"Manifest and signature file disagree: {platform}")
        if name not in verified:
            verify_signature((destination / name).read_bytes(), signature, public_packet)
            verified.add(name)
        print(f"Verified updater signature: {platform}")
    verify_macos(destination / "Claude.Switchboard_universal.app.tar.gz", version, config["identifier"])

    if not release["draft"]:
        latest = json.loads(gh("api", f"repos/{args.repo}/releases/latest"))
        if latest["tag_name"] == args.tag:
            for endpoint in config["plugins"]["updater"]["endpoints"]:
                with urlopen(endpoint, timeout=30) as response:
                    public_manifest = json.load(response)
                require(public_manifest["version"] == version, "Public updater endpoint serves another version")
                require(public_manifest["platforms"] == manifest["platforms"], "Public updater platforms differ")
                print("Verified public updater endpoint")
        else:
            print("Historical release: the current updater endpoint belongs to a different version")
    else:
        print("Draft assets verified; public updater check deferred until publication")
    print(json.dumps({"url": release["html_url"], "assets": len(assets), "version": version,
                      "verified_updater_bundles": sorted(verified)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", default="FeiXu-1131372/claude-switchboard")
    parser.add_argument("--config", type=Path, default=Path("src-tauri/tauri.conf.json"))
    parser.add_argument("--download-dir", type=Path, required=True, help="Scratch directory for release assets")
    parser.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()
    try:
        verify_release(args)
    except (ValueError, OSError, KeyError, IndexError, struct.error, tarfile.TarError) as error:
        parser.exit(1, f"Verification failed: {error}\n")


if __name__ == "__main__":
    main()
