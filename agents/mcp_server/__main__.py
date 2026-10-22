"""Run the football MCP server over stdio for one match."""

import argparse
import os
from pathlib import Path

from agents.mcp_server import MatchData, build


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--match-file", type=Path, help="JSONL: Match, then events")
    src.add_argument(
        "--database", action="store_true", help="the interpreter's Postgres (read only)"
    )
    parser.add_argument("--match-id", help="default: the latest match in the store")
    args = parser.parse_args(argv)
    if args.match_file:
        data = MatchData.from_file(args.match_file)
    else:
        from dotenv import load_dotenv

        from stream.interpreter.store import database_url

        load_dotenv()
        data = MatchData.from_postgres(
            os.environ.get("DATABASE_URL") or database_url(), args.match_id
        )
    build(data).run()


if __name__ == "__main__":
    main()
