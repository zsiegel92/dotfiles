#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Render select_git_branch rows as branch-tip ancestry views."""

import collections
import subprocess
import sys


def read_branch_rows():
    rows = []
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 4:
            continue

        rows.append({
            "branch": parts[0],
            "oid": parts[2],
            "marker": parts[3],
        })

    return rows


def commit_parent_map():
    try:
        result = subprocess.run(
            ["git", "rev-list", "--parents", "--branches"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.exit(exc.returncode)

    parents_by_commit = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts:
            parents_by_commit[parts[0]] = parts[1:]

    return parents_by_commit


def nearest_parent_indices(rows, parents_by_commit):
    tip_indices_by_oid = collections.defaultdict(list)
    for index, row in enumerate(rows):
        tip_indices_by_oid[row["oid"]].append(index)

    parent_indices = [None] * len(rows)

    for index, row in enumerate(rows):
        start_oid = row["oid"]
        queue = collections.deque()
        seen = {start_oid}

        for parent_oid in parents_by_commit.get(start_oid, []):
            if parent_oid not in seen:
                seen.add(parent_oid)
                queue.append(parent_oid)

        while queue:
            oid = queue.popleft()
            found_parent = None

            for candidate_index in tip_indices_by_oid.get(oid, []):
                if candidate_index != index and rows[candidate_index]["oid"] != start_oid:
                    found_parent = candidate_index
                    break

            if found_parent is not None:
                parent_indices[index] = found_parent
                break

            for parent_oid in parents_by_commit.get(oid, []):
                if parent_oid not in seen:
                    seen.add(parent_oid)
                    queue.append(parent_oid)

    return parent_indices


def nearest_parent_index_sets(rows, parents_by_commit):
    tip_indices_by_oid = collections.defaultdict(list)
    for index, row in enumerate(rows):
        tip_indices_by_oid[row["oid"]].append(index)

    parent_index_sets = [set() for _ in rows]

    for index, row in enumerate(rows):
        start_oid = row["oid"]
        queue = collections.deque()
        seen = {start_oid}

        for parent_oid in parents_by_commit.get(start_oid, []):
            if parent_oid not in seen:
                seen.add(parent_oid)
                queue.append(parent_oid)

        while queue:
            oid = queue.popleft()
            found_parent_indices = [
                candidate_index
                for candidate_index in tip_indices_by_oid.get(oid, [])
                if candidate_index != index and rows[candidate_index]["oid"] != start_oid
            ]

            if found_parent_indices:
                parent_index_sets[index].update(found_parent_indices)
                continue

            for parent_oid in parents_by_commit.get(oid, []):
                if parent_oid not in seen:
                    seen.add(parent_oid)
                    queue.append(parent_oid)

    return [sorted(parent_indices) for parent_indices in parent_index_sets]


def visible_branch(rows, index):
    branch = rows[index]["branch"]
    if rows[index]["marker"] == "*":
        return "* " + branch

    return branch


def branch_topological_order(rows, parent_index_sets):
    children = [[] for _ in rows]
    remaining_parent_counts = [len(parent_indices) for parent_indices in parent_index_sets]

    for child_index, parent_indices in enumerate(parent_index_sets):
        for parent_index in parent_indices:
            children[parent_index].append(child_index)

    ready = [index for index, parent_count in enumerate(remaining_parent_counts) if parent_count == 0]
    rendered = set()
    order = []

    while ready:
        ready.sort()
        index = ready.pop(0)
        if index in rendered:
            continue

        rendered.add(index)
        order.append(index)

        for child_index in sorted(children[index]):
            remaining_parent_counts[child_index] -= 1
            if remaining_parent_counts[child_index] == 0:
                ready.append(child_index)

    order.extend(index for index in range(len(rows)) if index not in rendered)
    return order


def print_tree_rows(rows, parent_indices):
    children = [[] for _ in rows]
    roots = []

    for index, parent_index in enumerate(parent_indices):
        if parent_index is None:
            roots.append(index)
        else:
            children[parent_index].append(index)

    rendered = set()

    def render(index, prefix, is_last, depth):
        if index in rendered:
            return

        rendered.add(index)
        row = rows[index]

        if depth == 0:
            display = visible_branch(rows, index)
            next_prefix = ""
        else:
            connector = "└─ " if is_last else "├─ "
            display = prefix + connector + visible_branch(rows, index)
            next_prefix = prefix + ("   " if is_last else "│  ")

        print("\t".join([row["branch"], display, row["oid"], row["marker"]]))

        child_indices = children[index]
        for child_position, child_index in enumerate(child_indices):
            render(child_index, next_prefix, child_position == len(child_indices) - 1, depth + 1)

    for root_index in roots:
        render(root_index, "", True, 0)

    for index in range(len(rows)):
        if index not in rendered:
            render(index, "", True, 0)


def print_full_dag_rows(rows, parent_index_sets):
    for index in branch_topological_order(rows, parent_index_sets):
        row = rows[index]
        parent_indices = parent_index_sets[index]
        display = visible_branch(rows, index)

        if parent_indices:
            parent_branches = ", ".join(rows[parent_index]["branch"] for parent_index in parent_indices)
            display = f"{display} <- {parent_branches}"

        print("\t".join([row["branch"], display, row["oid"], row["marker"]]))


def main():
    view = "tree"
    if len(sys.argv) > 1:
        if sys.argv[1] in {"--full-dag", "--dag", "full-dag", "dag"}:
            view = "full-dag"
        elif sys.argv[1] not in {"--tree", "tree"}:
            sys.stderr.write(f"unknown view: {sys.argv[1]}\n")
            sys.exit(2)

    rows = read_branch_rows()
    if not rows:
        return

    parents_by_commit = commit_parent_map()
    if view == "full-dag":
        print_full_dag_rows(rows, nearest_parent_index_sets(rows, parents_by_commit))
    else:
        print_tree_rows(rows, nearest_parent_indices(rows, parents_by_commit))


if __name__ == "__main__":
    main()
