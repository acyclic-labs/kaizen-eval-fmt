#!/usr/bin/env python3
"""Split the build and tests of a CI job into shards.

Usage: ci_shard.py K/N targets|tests

Run in a configured Ninja build directory. The leaf targets of `all` are
distributed round-robin across N shards; `targets` prints the targets of
shard K (1-based). `tests` prints a ctest regex matching the tests of shard
K: the tests whose executable is built in that shard plus a round-robin share
of the tests that don't have a target of their own. Together the shards build
everything `all` does and run every test `ctest` does.
"""

import json
import os
import re
import subprocess
import sys


def query(targets):
  """Returns a dict mapping each phony target to its explicit inputs."""
  out = subprocess.check_output(['ninja', '-t', 'query'] + targets, text=True)
  inputs = {}
  target = None
  phony = False
  for line in out.splitlines():
    if not line.startswith(' '):
      target = line.rstrip(':')
      phony = False
    elif line.strip() == 'input: phony':
      phony = True
      inputs[target] = []
    elif line.startswith('  ') and not line.startswith('    '):
      phony = False
    elif phony and not line.strip().startswith('|'):
      inputs[target].append(line.strip())
  return inputs


def leaf_targets(target='all'):
  """Returns the targets `target` builds, expanding phony `*all` targets."""
  leaves = []
  for input in query([target]).get(target, []):
    if input.endswith('/all'):
      leaves += leaf_targets(input)
    else:
      leaves.append(input)
  return leaves


def main():
  shard, count = map(int, sys.argv[1].split('/'))
  leaves = leaf_targets()
  mine = leaves[shard - 1::count]
  if sys.argv[2] == 'targets':
    print(' '.join(mine))
    return
  tests = [t['name'] for t in json.loads(subprocess.check_output(
      ['ctest', '--show-only=json-v1'], text=True))['tests']]
  built = {os.path.basename(t) for t in leaves}
  names = {os.path.basename(t) for t in mine}
  names.update([t for t in tests if t not in built][shard - 1::count])
  # Escape regex metacharacters; CMake regex doesn't accept escaped '-'.
  escape = lambda t: re.sub(r'([][.*+?^$(){}|\\])', r'\\\1', t)
  print('^(' + '|'.join(escape(t) for t in tests if t in names) + ')$')


if __name__ == '__main__':
  main()
