import argparse, sys
import textwrap
from typing import Any, Callable, Dict, List, Optional

from syncweb.log_utils import log
from syncweb.str_utils import safe_len


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        if isinstance(values, str):
            items.extend(values.split(","))  # type: ignore
        else:
            items.extend(flatten(s.split(",") for s in values))  # type: ignore

        setattr(namespace, self.dest, items)


class Subcommand:
    def __init__(
        self,
        name: str,
        help: str = "",
        aliases: Optional[List[str]] = None,
        func: Optional[Callable[[argparse.Namespace], Any]] = None,
    ):
        self.name = name
        self.help = help
        self.aliases = aliases or []
        self.func = func
        self._parser = argparse.ArgumentParser(prog=name, description=help, add_help=True)

    @property
    def all_names(self) -> List[str]:
        return [self.name, *self.aliases]

    def add_argument(self, *args, **kwargs):
        return self._parser.add_argument(*args, **kwargs)

    def set_defaults(self, **kwargs):
        self._parser.set_defaults(**kwargs)


class SubParser:
    def __init__(
        self,
        parser: Optional[argparse.ArgumentParser] = None,
        *,
        default_command: Optional[str] = None,
        version: Optional[str] = None,
    ):
        self.parser = parser or argparse.ArgumentParser()
        self.default_command = default_command
        self.version = version
        self.subcommands: Dict[str, Subcommand] = {}

    def add_argument(self, *args, **kwargs):
        return self.parser.add_argument(*args, **kwargs)

    def set_defaults(self, **kwargs):
        self.parser.set_defaults(**kwargs)

    def add_parser(
        self,
        name: str,
        *,
        help: str = "",
        aliases: Optional[List[str]] = None,
        func: Optional[Callable[[argparse.Namespace], Any]] = None,
    ) -> Subcommand:
        cmd = Subcommand(name, help, aliases, func)
        for n in cmd.all_names:
            if n in self.subcommands:
                raise ValueError(f"Duplicate subcommand name or alias: {n}")
            self.subcommands[n] = cmd
        return cmd

    def parse(self, argv: Optional[List[str]] = None):
        argv = argv or sys.argv[1:]

        if not argv and self.default_command:
            argv = [self.default_command]

        if not argv or argv[0] in ("-h", "--help", "help"):
            self.print_help()
            sys.exit(0)

        if self.version and argv[0] in ("-V", "--version"):
            print(self.version)
            sys.exit(0)

        cmd_index = next((i for i, arg in enumerate(argv) if not arg.startswith("-")), None)
        if cmd_index is None:
            self.error("No command provided")
        cmd_name = argv[cmd_index]
        cmd = self.subcommands.get(cmd_name)
        if not cmd:
            self.error(f"Unknown command: '{cmd_name}'")
        # global_argv = argv[:cmd_index]
        # subcmd_argv = argv[cmd_index + 1:]

        log.debug("argv: %s", argv)
        global_args, rest = self.parser.parse_known_args(argv)
        log.debug("global_args: %s", global_args)
        log.debug("cmd: %s, rest: %s", rest[0], rest[1:])

        # merge global args into subcommand parser
        for action in self.parser._actions:
            if action.option_strings:
                if any(opt in ("-h", "--help") for opt in action.option_strings):
                    continue
                cmd._parser._add_action(action)
        # parse command args
        args = cmd._parser.parse_args(rest[1:])
        for k, v in vars(global_args).items():
            if getattr(args, k, None) is None:
                setattr(args, k, v)

        parser_defaults = SubParser.get_argparse_defaults(self.parser)
        args.defaults = {k: v for k, v in args.__dict__.items() if parser_defaults.get(k, None) == v}
        settings = {
            k: v for k, v in args.__dict__.items() if k not in ["verbose", "defaults", *list(args.defaults.keys())]
        }
        if args:
            max_v = 140
            log.debug(
                {
                    k: (
                        v
                        if len(str(v)) < max_v
                        else textwrap.shorten(str(v), max_v, placeholder=f"[{safe_len(v)} items]")
                    )
                    for k, v in settings.items()
                }
            )

        if not cmd.func:
            self.error(f"Command '{cmd.name}' has no handler.")

        def run():
            if cmd.func:
                return cmd.func(args)

        args.run = run
        return args

    def print_help(self):
        print(f"{self.parser.description or ''}\n")
        print("Available commands:")
        for cmd in {v.name: v for v in self.subcommands.values()}.values():
            alias_text = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            print(f"  {cmd.name:<12} {cmd.help}{alias_text}")
        print("\nUse '%s <command> --help' for more information." % self.parser.prog)

    def error(self, msg: str):
        sys.stderr.write(f"error: {msg}\n")
        self.print_help()
        sys.exit(2)

    @staticmethod
    def get_argparse_defaults(parser):
        defaults = {}
        for action in parser._actions:
            if not action.required and action.default is not None and action.dest != "help":
                default = action.default
                if action.type is not None:
                    default = action.type(default)
                defaults[action.dest] = default
        return defaults
