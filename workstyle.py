"""Validate scoped preference updates and keep private state outside the skill package."""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_FILES = {"SKILL.md", "profile.md", "update-guide.md", "workstyle.py", "test_workstyle.py", "README.md", ".gitignore"}
SCOPES = {"communication", "execution", "review", "ui-design", "ui-copy", "visual-density", "maintenance", "privacy"}


def private_root():
    override = os.environ.get("WORKSTYLE_PRIVATE_DIR")
    home = Path(os.environ.get("CODEX_HOME", Path.home()/".codex"))
    root = Path(override).expanduser() if override else home/"private"/"workstyle-distill"
    package = Path(__file__).resolve().parent
    if root.resolve().is_relative_to(package):
        raise ValueError("Private state must remain outside the skill package.")
    return root


def read(root):
    path = root/"profile.json"
    if not path.exists():
        return {"schema_version": 1, "revision": 0, "rules": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or type(value.get("revision")) is not int:
        raise ValueError("Private profile schema is invalid.")
    validate({"rules": value.get("rules")})
    return value


def validate(candidate):
    rules = candidate.get("rules")
    if not isinstance(rules, list) or len(rules) > 40:
        raise ValueError("Provide at most 40 scoped rules.")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("kind") != "preference":
            raise ValueError("Only workstyle preferences can enter this profile.")
        name = rule.get("id", "")
        if not re.fullmatch(r"[a-z0-9-]{1,64}", name) or name in ids:
            raise ValueError("Rule identifiers must be unique and use lowercase hyphens.")
        ids.add(name)
        scope = rule.get("scope", "")
        if scope not in SCOPES and not re.fullmatch(r"project:[a-z0-9-]{1,64}", scope):
            raise ValueError("A supported, explicit rule scope is required.")
        if not isinstance(rule.get("text"), str) or not 1 <= len(rule["text"].strip()) <= 500:
            raise ValueError("Rule text must contain 1 to 500 characters.")
        evidence = rule.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("User evidence is required.")
        for item in evidence:
            if not isinstance(item, dict) or item.get("author") != "user" or type(item.get("direct")) is not bool:
                raise ValueError("Only user-authored evidence is accepted.")
            if not isinstance(item.get("source"), str) or not 1 <= len(item["source"]) <= 200:
                raise ValueError("Provide a short local evidence locator.")
        if not any(item["direct"] for item in evidence) and len({item["source"] for item in evidence}) < 2:
            raise ValueError("Inferred preferences need two independent user sources.")


def idle(snapshot):
    try:
        observed = datetime.fromisoformat(snapshot["observed_at"])
        age = (datetime.now(timezone.utc)-observed).total_seconds()
        threads = snapshot["threads"]
        return (snapshot.get("complete") is True and snapshot.get("online") is True
                and snapshot.get("new_input") is False and bool(snapshot.get("self_id"))
                and 0 <= age <= 120 and isinstance(threads, list)
                and any(isinstance(item, dict) and item.get("id") == snapshot["self_id"] for item in threads)
                and all(isinstance(item, dict) and bool(item.get("id"))
                        and (item["id"] == snapshot["self_id"] or item.get("status") in {"idle", "notLoaded", "completed"})
                        for item in threads))
    except (KeyError, TypeError, ValueError):
        return False


def apply(root, candidate, expected_revision, mode="explicit", gate=None):
    validate(candidate)
    if mode not in {"explicit", "background"}:
        raise ValueError("Choose explicit or background mode.")
    if mode == "background" and not idle(gate or {}):
        raise ValueError("Background update skipped: fresh idle evidence is unavailable.")
    root.mkdir(parents=True, exist_ok=True)
    lock = root/"update.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Update skipped: another writer owns the lock.") from None
    try:
        os.close(fd)
        current = read(root)
        if current["revision"] != expected_revision:
            raise ValueError("Profile changed. Read and merge the latest revision.")
        rules = {item["id"]: item for item in current["rules"]}
        for incoming in candidate["rules"]:
            item = {key: value for key, value in incoming.items() if key != "supersedes"}
            target = incoming.get("supersedes", item["id"])
            old = rules.get(target)
            if old and old != item:
                if incoming.get("supersedes") != target or old["scope"] != item["scope"]:
                    raise ValueError("A change must explicitly replace a rule in the same scope.")
                if not any(source["direct"] for source in item["evidence"]):
                    raise ValueError("Replacing a rule requires an explicit user correction.")
                del rules[target]
            if item["id"] in rules and rules[item["id"]] != item:
                raise ValueError("Rule identifier conflict requires review.")
            rules[item["id"]] = item
        merged = list(rules.values())
        validate({"rules": merged})
        if merged == current["rules"]:
            return current
        now = datetime.now(timezone.utc)
        if mode == "background" and current.get("last_background_at"):
            elapsed = (now-datetime.fromisoformat(current["last_background_at"])).total_seconds()
            if elapsed < 86400:
                raise ValueError("Background update skipped: the 24-hour interval has not elapsed.")
        next_value = {**current, "revision": current["revision"]+1, "rules": merged}
        if mode == "background":
            next_value["last_background_at"] = now.isoformat()
        temporary = root/"profile.pending"
        try:
            temporary.write_text(json.dumps(next_value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            os.replace(temporary, root/"profile.json")
        finally:
            temporary.unlink(missing_ok=True)
        return next_value
    finally:
        lock.unlink()


def public_findings(root):
    findings = []
    patterns = {
        "private-address": r"https?://(?:localhost|127\.0\.0\.1|10\.(?:\d+\.){2}\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
        "personal-path": r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+",
        "credential": r"(?:credential|password|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_+/.-]{6,}",
        "private-key": r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
        "token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b",
    }
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if path.is_symlink():
            findings.append((str(relative), 0, "symbolic-link"))
            continue
        if not path.is_file():
            continue
        if relative.as_posix() not in PUBLIC_FILES:
            findings.append((str(relative), 0, "non-public-file"))
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, pattern in patterns.items():
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append((str(relative), number, label))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("paths")
    commands.add_parser("show")
    check = commands.add_parser("check-public")
    check.add_argument("--root", type=Path, default=Path(__file__).parent)
    update = commands.add_parser("apply")
    update.add_argument("--candidate", type=Path, required=True)
    update.add_argument("--expected-revision", type=int, required=True)
    update.add_argument("--mode", choices=["explicit", "background"], default="explicit")
    update.add_argument("--gate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check-public":
            findings = public_findings(args.root)
            print(json.dumps({"ok": not findings, "findings": findings}))
            return int(bool(findings))
        root = private_root()
        if args.command == "paths":
            print(json.dumps({"private_dir": str(root), "profile": str(root/"profile.json")}))
        elif args.command == "show":
            print(json.dumps(read(root), ensure_ascii=False, indent=2))
        else:
            if not args.candidate.resolve().is_relative_to(root.resolve()):
                raise ValueError("Candidate evidence must remain in the private directory.")
            if args.gate and not args.gate.resolve().is_relative_to(root.resolve()):
                raise ValueError("Task state must remain in the private directory.")
            gate = json.loads(args.gate.read_text(encoding="utf-8")) if args.gate else None
            value = apply(root, json.loads(args.candidate.read_text(encoding="utf-8")), args.expected_revision, args.mode, gate)
            print(json.dumps({"revision": value["revision"], "rules": len(value["rules"])}))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
