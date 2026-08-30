"""Classify CLI commands before GHOST executes them.

The policy is intentionally deterministic. Commands that are proven read-only
run immediately. Commands that can mutate state, execute hidden subcommands, or
cannot be proven read-only require confirmation.

GHOST CLI normally executes through Bash/WSL. This classifier therefore gives
broad Green coverage to common Bash/Linux inspection commands while keeping
state-changing variants behind confirmation.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


_ALWAYS_READ_ONLY_COMMANDS = frozenset(
    {
        ":",
        "[",
        "basename",
        "cat",
        "column",
        "comm",
        "cmp",
        "cd",
        "cut",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "false",
        "fmt",
        "fold",
        "free",
        "getent",
        "grep",
        "groups",
        "head",
        "id",
        "join",
        "jq",
        "locate",
        "ls",
        "lsattr",
        "lscpu",
        "lsblk",
        "lsof",
        "lspci",
        "lsusb",
        "md5sum",
        "mountpoint",
        "nl",
        "paste",
        "pgrep",
        "pidof",
        "printenv",
        "printf",
        "ps",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "sha256sum",
        "sleep",
        "sort",
        "ss",
        "strings",
        "stat",
        "tail",
        "test",
        "tr",
        "tree",
        "true",
        "type",
        "uname",
        "uptime",
        "vmstat",
        "wc",
        "whereis",
        "which",
        "who",
        "whoami",
        "uniq",
    }
)

_CONFIRMATION_PROFILES = frozenset({"strict", "trusted_local"})

_DANGEROUS_EXECUTABLES = frozenset(
    {
        "bcdedit.exe",
        "chgrp",
        "chmod",
        "chown",
        "dd",
        "del",
        "diskpart.exe",
        "erase",
        "fdisk",
        "halt",
        "kill",
        "mkfs",
        "parted",
        "pkill",
        "poweroff",
        "reboot",
        "reg.exe",
        "rm",
        "rmdir",
        "shutdown",
        "shred",
        "sudo",
        "taskkill.exe",
    }
)

_SED_READ_ONLY_SCRIPT = re.compile(
    r"(?:\d+|\$)(?:,(?:\d+|\$))?[pqd]?"
)

_FIND_WRITE_ACTIONS = frozenset(
    {
        "-delete",
        "-exec",
        "-execdir",
        "-fls",
        "-fprint",
        "-fprintf",
        "-ok",
        "-okdir",
    }
)

_FD_EXEC_OPTIONS = frozenset(
    {
        "-x",
        "-X",
        "--exec",
        "--exec-batch",
    }
)

_GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "cat-file",
        "count-objects",
        "describe",
        "diff",
        "for-each-ref",
        "grep",
        "log",
        "ls-files",
        "ls-tree",
        "name-rev",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
    }
)

_SYSTEMCTL_READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "cat",
        "is-active",
        "is-enabled",
        "is-failed",
        "list-dependencies",
        "list-unit-files",
        "list-units",
        "show",
        "status",
    }
)

_POWERCFG_READ_ONLY_OPTIONS = frozenset(
    {
        "/a",
        "/availablesleepstates",
        "/getactivescheme",
        "/l",
        "/list",
        "/query",
        "/requests",
    }
)

_SHELL_SEGMENT_PATTERN = re.compile(r"(?:&&|\|\||[;|\n])")
_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*=.*",
    re.DOTALL,
)
_SAFE_FD_REDIRECTION_PATTERN = re.compile(
    r"(?:(?:\d+)?[<>]&\d+)"
)


@dataclass(frozen=True)
class CommandDecision:
    """Report whether an exact command requires user confirmation."""

    confirmation_required: bool
    reason: str


class CommandPolicy:
    """Apply a deterministic read-only policy without permanently blocking commands."""

    def classify(
        self,
        command: str,
        confirmation_profile: str = "strict",
    ) -> CommandDecision:
        """Validate and classify one complete shell command."""
        clean_command = self._require_command(command)
        profile = str(confirmation_profile or "").strip().lower()
        if profile not in _CONFIRMATION_PROFILES:
            raise ValueError(
                "confirmation_profile must be 'strict' or 'trusted_local'"
            )

        if profile == "trusted_local":
            dangerous_reason = self._dangerous_command_reason(clean_command)
            if dangerous_reason is not None:
                return CommandDecision(True, dangerous_reason)
            return CommandDecision(
                False,
                "trusted_local permits commands not classified as dangerous",
            )

        shell_reason = self._unsafe_shell_syntax_reason(clean_command)
        if shell_reason is not None:
            return CommandDecision(True, shell_reason)

        segments = _SHELL_SEGMENT_PATTERN.split(clean_command)

        for segment in segments:
            reason = self._segment_confirmation_reason(segment)
            if reason is not None:
                return CommandDecision(True, reason)

        return CommandDecision(
            False,
            "command is classified as read-only",
        )

    def _dangerous_command_reason(self, command: str) -> str | None:
        if any(marker in command for marker in ("`", "$(")):
            return "hidden command substitution requires confirmation"

        for segment in _SHELL_SEGMENT_PATTERN.split(command):
            try:
                tokens = shlex.split(segment, posix=True)
            except ValueError:
                return "unparseable shell syntax requires confirmation"
            tokens = self._remove_environment_prefix(tokens)
            if not tokens:
                continue

            executable = tokens[0].rsplit("/", 1)[-1].lower()
            arguments = [argument.lower() for argument in tokens[1:]]
            if executable in _DANGEROUS_EXECUTABLES or executable.startswith(
                "mkfs."
            ):
                return f"{executable!r} is classified as dangerous"
            if executable == "git" and arguments[:1] in (
                ["push"],
                ["clean"],
            ):
                return f"git {arguments[0]} requires confirmation"
            if executable == "git" and arguments[:2] == ["reset", "--hard"]:
                return "git reset --hard requires confirmation"
            if executable == "docker" and arguments[:1] in (
                ["rm"],
                ["rmi"],
                ["prune"],
            ):
                return f"docker {arguments[0]} requires confirmation"
            if executable == "docker" and arguments[:2] == ["system", "prune"]:
                return "docker system prune requires confirmation"
            if executable == "systemctl" and arguments[:1] in (
                ["disable"],
                ["mask"],
                ["poweroff"],
                ["reboot"],
                ["restart"],
                ["stop"],
            ):
                return f"systemctl {arguments[0]} requires confirmation"

        return None

    @staticmethod
    def _require_command(command: str) -> str:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        return command.strip()

    @staticmethod
    def _unsafe_shell_syntax_reason(
        command: str,
    ) -> str | None:
        if any(marker in command for marker in ("`", "$(")):
            return (
                "command substitution can execute "
                "unclassified commands"
            )

        command_without_safe_fd_redirects = (
            _SAFE_FD_REDIRECTION_PATTERN.sub(
                "",
                command,
            )
        )

        if ">" in command_without_safe_fd_redirects:
            return "output redirection can write data"

        if re.search(r"(?<!&)&(?!&)", command):
            return (
                "background shell execution "
                "requires confirmation"
            )

        return None

    def _segment_confirmation_reason(
        self,
        segment: str,
    ) -> str | None:
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            return (
                "the shell command could not "
                "be classified safely"
            )

        tokens = self._remove_environment_prefix(tokens)

        if not tokens:
            return (
                "the shell command could not "
                "be classified safely"
            )

        executable = tokens[0].rsplit("/", 1)[-1]
        arguments = tokens[1:]

        if executable in _ALWAYS_READ_ONLY_COMMANDS:
            return None

        if executable == "find":
            return self._classify_find(arguments)

        if executable == "sed":
            return self._classify_sed(arguments)

        if executable in {"fd", "fdfind"}:
            return self._classify_fd(arguments)

        if executable == "date":
            return self._classify_date(arguments)

        if executable == "dmesg":
            return self._classify_dmesg(arguments)

        if executable == "file":
            return self._classify_file(arguments)

        if executable == "hostname":
            return self._classify_hostname(arguments)

        if executable == "git":
            return self._classify_git(arguments)

        if executable == "docker":
            return self._classify_docker(arguments)

        if executable == "systemctl":
            return self._classify_systemctl(arguments)

        if executable == "journalctl":
            return self._classify_journalctl(arguments)

        if executable == "ip":
            return self._classify_ip(arguments)

        if executable == "command":
            return self._classify_command_builtin(arguments)

        if executable in {
            "hostname.exe",
            "whoami.exe",
            "where.exe",
            "tasklist.exe",
            "systeminfo.exe",
        }:
            return None

        if executable.lower() == "powercfg.exe":
            return self._classify_powercfg(arguments)

        return (
            f"{executable!r} is not classified "
            "as a read-only command"
        )

    @staticmethod
    def _classify_sed(arguments: list[str]) -> str | None:
        scripts: list[str] = []
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument in {"-i", "--in-place"} or argument.startswith(
                ("-i", "--in-place=")
            ):
                return "sed in-place editing can write data"
            if argument in {"-f", "--file"} or argument.startswith(
                "--file="
            ):
                return "sed script files cannot be proven read-only"
            if argument in {"-e", "--expression"}:
                index += 1
                if index >= len(arguments):
                    return "sed expression is missing"
                scripts.append(arguments[index])
            elif argument.startswith("--expression="):
                scripts.append(argument.split("=", 1)[1])
            elif not argument.startswith("-") and not scripts:
                scripts.append(argument)
            index += 1

        if not scripts:
            return "sed expression could not be classified"
        if all(_SED_READ_ONLY_SCRIPT.fullmatch(script.strip()) for script in scripts):
            return None
        return "sed expression is not proven read-only"

    @staticmethod
    def _remove_environment_prefix(
        tokens: list[str],
    ) -> list[str]:
        remaining = list(tokens)

        while (
            remaining
            and _ENV_ASSIGNMENT_PATTERN.fullmatch(
                remaining[0]
            )
        ):
            remaining.pop(0)

        return remaining

    @staticmethod
    def _classify_find(
        arguments: list[str],
    ) -> str | None:
        if any(
            argument in _FIND_WRITE_ACTIONS
            for argument in arguments
        ):
            return (
                "find contains an action that can "
                "write or execute commands"
            )

        return None

    @staticmethod
    def _classify_fd(
        arguments: list[str],
    ) -> str | None:
        if any(
            argument in _FD_EXEC_OPTIONS
            for argument in arguments
        ):
            return (
                "fd contains an option "
                "that executes commands"
            )

        if any(
            argument.startswith("--exec=")
            or argument.startswith("--exec-batch=")
            for argument in arguments
        ):
            return (
                "fd contains an option "
                "that executes commands"
            )

        return None

    @staticmethod
    def _classify_date(
        arguments: list[str],
    ) -> str | None:
        if any(
            argument in {"-s", "--set"}
            or argument.startswith("--set=")
            for argument in arguments
        ):
            return (
                "date contains an option "
                "that can change system time"
            )

        return None

    @staticmethod
    def _classify_dmesg(
        arguments: list[str],
    ) -> str | None:
        if any(
            argument in {
                "-c",
                "--read-clear",
                "-C",
                "--clear",
            }
            for argument in arguments
        ):
            return (
                "dmesg contains an option that "
                "can clear the kernel log buffer"
            )

        return None

    @staticmethod
    def _classify_file(
        arguments: list[str],
    ) -> str | None:
        if any(
            argument in {"-C", "--compile"}
            or argument.startswith("--compile=")
            for argument in arguments
        ):
            return (
                "file contains an option that can "
                "write a compiled magic database"
            )

        return None

    @staticmethod
    def _classify_hostname(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        if all(
            argument.startswith("-")
            for argument in arguments
        ):
            return None

        return (
            "hostname with a hostname argument "
            "can change system state"
        )

    @staticmethod
    def _classify_git(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        subcommand = arguments[0]
        rest = arguments[1:]

        if subcommand in _GIT_READ_ONLY_SUBCOMMANDS:
            return None

        if (
            subcommand == "remote"
            and rest in (
                [],
                ["-v"],
                ["--verbose"],
            )
        ):
            return None

        if subcommand == "branch":
            if not rest:
                return None

            if rest == ["--show-current"]:
                return None

            if rest[:1] == ["--list"]:
                return None

        if subcommand == "tag":
            if not rest:
                return None

            if rest[:1] in (
                ["--list"],
                ["-l"],
            ):
                return None

        if subcommand == "config" and rest:
            read_options = {
                "--get",
                "--get-all",
                "--get-regexp",
                "--get-urlmatch",
                "--list",
                "-l",
            }

            if rest[0] in read_options:
                return None

        return (
            f"git {subcommand} can change "
            "repository or remote state"
        )

    @staticmethod
    def _classify_docker(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        subcommand = arguments[0]
        rest = arguments[1:]

        if subcommand in {
            "images",
            "info",
            "inspect",
            "logs",
            "ps",
            "stats",
            "top",
            "version",
        }:
            return None

        nested_read_only = {
            "container": {
                "inspect",
                "list",
                "logs",
                "ls",
                "stats",
                "top",
            },
            "image": {
                "history",
                "inspect",
                "list",
                "ls",
            },
            "network": {
                "inspect",
                "list",
                "ls",
            },
            "node": {
                "inspect",
                "list",
                "ls",
                "ps",
            },
            "system": {
                "df",
                "info",
            },
            "volume": {
                "inspect",
                "list",
                "ls",
            },
        }

        if subcommand in nested_read_only:
            nested = rest[0] if rest else "ls"

            if nested in nested_read_only[subcommand]:
                return None

        return (
            f"docker {subcommand} "
            "can change Docker state"
        )

    @staticmethod
    def _classify_systemctl(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        subcommand = arguments[0]

        if subcommand in _SYSTEMCTL_READ_ONLY_SUBCOMMANDS:
            return None

        return (
            f"systemctl {subcommand} "
            "can change service state"
        )

    @staticmethod
    def _classify_journalctl(
        arguments: list[str],
    ) -> str | None:
        write_options = (
            "--flush",
            "--relinquish-var",
            "--rotate",
            "--setup-keys",
            "--sync",
            "--vacuum-",
        )

        if any(
            argument == option
            or argument.startswith(option)
            for argument in arguments
            for option in write_options
        ):
            return (
                "journalctl contains an option "
                "that can change journal state"
            )

        return None

    @staticmethod
    def _classify_ip(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        object_name = arguments[0]
        action = (
            arguments[1]
            if len(arguments) > 1
            else ""
        )

        if (
            object_name in {"address", "addr"}
            and action in {"", "show", "list"}
        ):
            return None

        if (
            object_name == "link"
            and action in {"", "show", "list"}
        ):
            return None

        if (
            object_name == "route"
            and action in {
                "",
                "show",
                "list",
                "get",
            }
        ):
            return None

        if (
            object_name == "rule"
            and action in {
                "",
                "show",
                "list",
            }
        ):
            return None

        if (
            object_name in {"neigh", "neighbor"}
            and action in {
                "",
                "show",
            }
        ):
            return None

        if object_name == "monitor":
            return None

        return (
            "the ip command can change network "
            "state or is not proven read-only"
        )

    @staticmethod
    def _classify_command_builtin(
        arguments: list[str],
    ) -> str | None:
        if arguments[:1] in (
            ["-v"],
            ["-V"],
        ):
            return None

        return (
            "the command builtin "
            "can execute another command"
        )

    @staticmethod
    def _classify_powercfg(
        arguments: list[str],
    ) -> str | None:
        if not arguments:
            return None

        first = arguments[0].lower()

        if first in _POWERCFG_READ_ONLY_OPTIONS:
            return None

        return (
            "powercfg.exe operation can "
            "change Windows power state"
        )
