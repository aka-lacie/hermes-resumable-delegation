"""Run through the target Hermes checkout's scripts/run_tests.sh from that checkout."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
