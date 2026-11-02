"""Public execution contract; AST execution lives in runtime, parsing in legacy helpers."""
from .legacy_engine import Unsupported, parse_table, compare
from .runtime import run, table, clean, CAPABILITIES
