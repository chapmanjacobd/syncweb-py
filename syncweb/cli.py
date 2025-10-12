import argparse, json, shlex, sys, textwrap
from itertools import zip_longest
from typing import Any, Callable, Dict, List, Optional

from syncweb import consts
from syncweb.log_utils import log
from syncweb.str_utils import flatten, safe_len

STDIN_DASH = ["-"]


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        if isinstance(values, str):
            items.extend(values.split(","))  # type: ignore
        else:
            items.extend(flatten(s.split(",") for s in values))  # type: ignore

        setattr(namespace, self.dest, items)


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == STDIN_DASH:
            print(f"{parser.prog}: Reading from stdin...", file=sys.stderr)
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)


class Subcommand:
    def __init__(
        self,
        name: str,
        help: str = "",
        aliases: Optional[List[str]] = None,
        func: Optional[Callable[[argparse.Namespace], Any]] = None,
        formatter_class=None,
    ):
        self.name = name
        self.help = help
        self.aliases = aliases or []
        self.func = func
        # Set add_help=False to handle help manually
        formatter = formatter_class or (lambda prog: argparse.RawTextHelpFormatter(prog, max_help_position=40))
        self._parser = argparse.ArgumentParser(prog=name, description=help, add_help=False, formatter_class=formatter)

    @property
    def all_names(self) -> List[str]:
        return [self.name, *self.aliases]

    def add_argument(self, *args, **kwargs):
        return self._parser.add_argument(*args, **kwargs)

    def set_defaults(self, **kwargs):
        self._parser.set_defaults(**kwargs)

    def print_help(self):
        """Print help for this subcommand"""
        self._parser.print_help()


def type_to_str(t):
    type_dict = {
        int: "Integer",
        float: "Float",
        bool: "Boolean",
        str: "String",
        list: "List",
        tuple: "Tuple",
        dict: "Dictionary",
        set: "Set",
    }
    _type = type_dict.get(t)

    if _type is None and getattr(t, "__annotations__", False):
        _type = type_dict.get(t.__annotations__["return"])
    if _type is None:
        _type = "Value"

    return _type.upper()


def format_two_columns(text1, text2, width1=25, width2=75, left_gutter=2, middle_gutter=2, right_gutter=3):
    terminal_width = min(consts.TERMINAL_SIZE.columns, 120) - (left_gutter + middle_gutter + right_gutter)
    if text2:
        width1 = int(terminal_width * (width1 / (width1 + width2)))
        width2 = int(terminal_width * (width2 / (width1 + width2)))
    else:
        width1 = terminal_width

    wrapped_text1 = []
    for t in text1.strip().split("\n"):
        if len(t) <= width1:
            wrapped_text1.append(t)
        else:
            wrapped_text1.extend(textwrap.wrap(t, width=width1, break_on_hyphens=False))

    wrapped_text2 = []
    for t in text2.split("\n"):
        if len(t) <= width2:
            wrapped_text2.append(t)
        else:
            wrapped_text2.extend(textwrap.wrap(t, width=width2, break_on_hyphens=False))

    formatted_lines = [
        f"{' ' * left_gutter}{line1:<{width1}}{' ' * middle_gutter}{line2:<{width2}}{' ' * right_gutter}".rstrip()
        for line1, line2 in zip_longest(wrapped_text1, wrapped_text2, fillvalue="")
    ]

    return "\n".join(formatted_lines) + "\n"


def default_to_str(obj):
    if obj is None:
        return None
    elif isinstance(obj, (list, tuple, set)):
        if len(obj) == 0:
            return None
        else:
            return '"' + ", ".join(shlex.quote(s) for s in obj) + '"'
    elif isinstance(obj, dict):
        return json.dumps(obj)
    if isinstance(obj, str):
        return '"' + str(obj) + '"'
    else:
        return str(obj)


class CustomHelpFormatter(argparse.RawTextHelpFormatter):
    def _metavar_formatter(self, action, default_metavar):
        if action.metavar is not None:
            result = action.metavar
        elif action.choices is not None:
            choice_strs = [str(choice) for choice in action.choices]
            result = "{%s}" % " ".join(choice_strs)
        else:
            result = default_metavar

        def format(tuple_size):  # noqa: A001
            if isinstance(result, tuple):
                return result
            else:
                return (result,) * tuple_size

        return format

    def _format_args(self, action, default_metavar):
        get_metavar = self._metavar_formatter(action, default_metavar)
        if action.nargs == argparse.ZERO_OR_MORE:
            result = "[%s ...]" % get_metavar(1)
        elif action.nargs == argparse.ONE_OR_MORE:
            result = "%s ..." % get_metavar(1)
        else:
            result = super()._format_args(action, default_metavar)
        return result

    def _format_default(self, action, opts):
        default = ""
        if action.default is not None:
            if isinstance(action, argparse.BooleanOptionalAction):
                if action.default:
                    default = opts[0]
                else:
                    default = opts[1]
            elif isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                pass
            elif action.default == "":
                pass
            else:
                default = default_to_str(action.default)
        return default

    def _format_usage(self, usage, actions, groups, prefix):
        if usage is None:
            return super()._format_usage(usage, actions, groups, prefix)

        return "usage: %s\n\n" % usage

    def _format_action(self, action):
        help_text = self._expand_help(action) if action.help else ""

        if help_text == "show this help message and exit":
            return ""  # not very useful self-referential humor

        subactions = [self._format_action(subaction) for subaction in self._iter_indented_subactions(action)]

        opts = action.option_strings
        if not opts and not help_text:
            return ""
        elif not opts:  # positional with help text
            opts = [action.dest.upper()]

        if len(opts) == 1:
            left = opts[0]
        elif isinstance(action, argparse.BooleanOptionalAction):
            left = f"{opts[0]} / {opts[1]}"
        elif opts[-1].startswith("--"):
            left = opts[0]
        else:
            left = f"{opts[0]} ({opts[-1]})"

        left += "\n  " + self._format_args(action, type_to_str(action.type or str))
        left += "\n"

        default = self._format_default(action, opts)
        const = default_to_str(action.const)

        extra = []
        if default:
            extra.append(f"default: {default}")
        if not isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)) and const:
            extra.append(f"const: {const}")
        extra = "; ".join(extra)

        extra = extra.rstrip()
        if extra:
            help_text = help_text or ""
            if help_text:
                help_text += " "
            help_text += f"({extra})"

        return "".join(subactions) + format_two_columns(left, help_text)


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
        self.formatter_class = CustomHelpFormatter
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
        cmd = Subcommand(name, help, aliases, func, formatter_class=self.formatter_class)
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

        # Check if help is requested for this subcommand
        if any(arg in ("-h", "--help") for arg in argv[cmd_index + 1 :]):
            # merge global args into subcommand parser for help display
            for action in self.parser._actions:
                if action.option_strings and action.dest != "help":
                    cmd._parser._add_action(action)
            cmd._parser.add_argument("-h", "--help", action="help", help="show this help message and exit")
            cmd.print_help()
            sys.exit(0)

        log.debug("argv: %s", argv)
        global_args, rest = self.parser.parse_known_args(argv)
        log.debug("global_args: %s", global_args)
        log.debug("cmd: %s, rest: %s", rest[0], rest[1:])

        # merge global args into subcommand parser
        for action in self.parser._actions:
            if action.option_strings and action.dest != "help":
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
