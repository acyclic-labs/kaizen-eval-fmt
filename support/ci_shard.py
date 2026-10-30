#!/usr/bin/env python3
"""Split the build and tests of a CI job into shards.

Usage: ci_shard.py K/N targets|tests

Run in a configured Ninja build directory. The leaf targets of `all` are
distributed across N shards, balanced by an estimate of their compile cost;
`targets` prints the targets of shard K (1-based). `tests` prints a ctest
regex matching the tests of shard K: the tests whose executable is built in
that shard plus a round-robin share of the tests that don't have a target of
their own. Together the shards build everything `all` does and run every test
`ctest` does.
"""

import json
import os
import re
import subprocess
import sys

# Estimated compile cost of an object file, in bytes of source, on top of the
# size of the source itself: every test includes fmt and gtest headers.
OBJECT_COST = 10000


def query(targets):
  """Returns a dict mapping each target to its explicit and other inputs."""
  out = subprocess.check_output(['ninja', '-t', 'query'] + targets, text=True)
  inputs = {}
  target = None
  section = None
  for line in out.splitlines():
    if not line.startswith(' '):
      target = line.rstrip(':')
      inputs[target] = ([], [])
    elif not line.startswith('    '):
      section = line.split(':')[0].strip()
    elif section == 'input':
      name = line.strip()
      if name.startswith('|'):
        inputs[target][1].append(name.lstrip('| '))
      else:
        inputs[target][0].append(name)
  return inputs


def leaf_targets(target='all'):
  """Returns the targets `target` builds, expanding phony `*all` targets."""
  leaves = []
  for input in query([target])[target][0]:
    if input.endswith('/all'):
      leaves += leaf_targets(input)
    else:
      leaves.append(input)
  return leaves


def partition(leaves, count):
  """Splits leaves into count shards with about the same compile cost."""
  graph = query(leaves)
  deps = {d for t in leaves for d in graph[t][1]}
  objects = {t: [i for i in graph[t][0] if i.endswith('.o')] for t in leaves}
  sources = query([o for t in leaves for o in objects[t]])
  def cost(target):
    # Targets other leaves depend on are built in every shard that needs them.
    if target in deps:
      return 0
    return sum(OBJECT_COST + sum(os.path.getsize(s) for s in sources[o][0]
                                 if os.path.isfile(s))
               for o in objects[target])
  shards = [[] for i in range(count)]
  costs = [0] * count
  for target in sorted(leaves, key=cost, reverse=True):
    i = costs.index(min(costs))
    shards[i].append(target)
    costs[i] += cost(target)
  return shards


def main():
  shard, count = map(int, sys.argv[1].split('/'))
  leaves = leaf_targets()
  mine = partition(leaves, count)[shard - 1]
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
