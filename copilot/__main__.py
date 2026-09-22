import argparse
import json
from pathlib import Path

from copilot.agent import run_case
from copilot.data import DEFAULT_SOURCE, ExcelProvider

parser = argparse.ArgumentParser(description="回放一条会话，输出数据、规则证据与本地回复草稿")
parser.add_argument("--session", default="S00268")
parser.add_argument("--cutoff", default=None)
parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
args = parser.parse_args()
print(json.dumps(run_case(ExcelProvider(args.source), args.session, args.cutoff), ensure_ascii=False, indent=2))
