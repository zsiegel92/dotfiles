#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Render select_git_branch rows as branch-tip ancestry views."""

import collections
import re
import subprocess
import sys

ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
PREVIEW_DECORATION_MARKER = "__GBS_BRANCH_PREVIEW__"
GIT_GRAPH_CONNECTOR_LINE_LIMIT = 2


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


def local_branch_rows():
    try:
        result = subprocess.run(
            ["git", "branch", "--format=%(HEAD)%09%(refname:short)%09%(objectname)"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.exit(exc.returncode)

    rows = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue

        rows.append({
            "branch": parts[1],
            "oid": parts[2],
            "marker": "*" if parts[0] == "*" else " ",
        })

    return rows


def local_branch_names():
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.exit(exc.returncode)

    return {line for line in result.stdout.splitlines() if line}


def strip_ansi(text):
    return ANSI_ESCAPE_PATTERN.sub("", text)


def decoration_branch_names(decorations, branch_names):
    names = []
    for decoration in strip_ansi(decorations).strip().split(", "):
        if decoration.startswith("HEAD -> "):
            decoration = decoration.removeprefix("HEAD -> ")
        if decoration in branch_names:
            names.append(decoration)

    return names


def should_print_unnamed_graph_line(line):
    plain_line = strip_ansi(line).strip()
    return plain_line and "*" not in plain_line


def preview_graph_lines(raw_output, branch_names, include_before_main):
    for line in raw_output.splitlines():
        if PREVIEW_DECORATION_MARKER in line:
            graph_prefix, decorations = line.split(PREVIEW_DECORATION_MARKER, 1)
            line_branch_names = decoration_branch_names(decorations, branch_names)
            if line_branch_names:
                yield graph_prefix + decorations

            if not include_before_main and "main" in line_branch_names:
                return
        elif should_print_unnamed_graph_line(line):
            yield line


def graph_continuation_prefix(graph_prefix):
    return " " * len(strip_ansi(graph_prefix))


def print_git_graph_connector_rows(connector_lines):
    if len(connector_lines) > GIT_GRAPH_CONNECTOR_LINE_LIMIT:
        return

    for line in connector_lines:
        print("\t".join(["", line, "", " "]))


def print_git_graph_rows():
    branch_names = local_branch_names()
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--graph",
                "--color=always",
                "--decorate=short",
                "--decorate-refs=refs/heads",
                "--simplify-by-decoration",
                "--sparse",
                f"--pretty=format:{PREVIEW_DECORATION_MARKER}%C(auto)%D%C(reset)",
                "--branches",
                "--",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.exit(exc.returncode)

    pending_connector_lines = []
    for line in result.stdout.splitlines():
        if PREVIEW_DECORATION_MARKER in line:
            graph_prefix, decorations = line.split(PREVIEW_DECORATION_MARKER, 1)
            line_branch_names = decoration_branch_names(decorations, branch_names)
            if line_branch_names:
                print_git_graph_connector_rows(pending_connector_lines)
                pending_connector_lines = []

            for branch_position, branch in enumerate(line_branch_names):
                if branch_position == 0:
                    display = graph_prefix + branch
                else:
                    display = graph_continuation_prefix(graph_prefix) + branch

                print("\t".join([branch, display, "", " "]))
        elif should_print_unnamed_graph_line(line):
            pending_connector_lines.append(line)


def print_branch_ancestry_preview(branch, include_before_main=False):
    if not branch:
        print("select a branch to see its ancestry")
        return

    branch_names = local_branch_names()
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--graph",
                "--color=always",
                "--decorate=short",
                "--decorate-refs=refs/heads",
                "--simplify-by-decoration",
                "--sparse",
                f"--pretty=format:{PREVIEW_DECORATION_MARKER}%C(auto)%D%C(reset)",
                branch,
                "--",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.exit(exc.returncode)

    for line in preview_graph_lines(result.stdout, branch_names, include_before_main):
        print(line)


def print_branch_parent_diff(parent_branch, branch):
    print(f"{parent_branch}..{branch}")
    result = subprocess.run(
        ["git", "diff", "--name-status", "--color=always", f"{parent_branch}..{branch}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)

    output = result.stdout.rstrip("\n")
    if output:
        print(output)
    else:
        print("(no file changes)")


def print_branch_parent_diff_preview(branch, view):
    if not branch:
        print("select a branch to see files changed vs its parent")
        return

    rows = local_branch_rows()
    selected_index = next(
        (index for index, row in enumerate(rows) if row["branch"] == branch),
        None,
    )
    if selected_index is None:
        print(f"branch not found: {branch}")
        return

    parents_by_commit = commit_parent_map()
    if view == "full-dag":
        parent_indices = nearest_parent_index_sets(rows, parents_by_commit)[selected_index]
    else:
        parent_index = nearest_parent_indices(rows, parents_by_commit)[selected_index]
        parent_indices = [] if parent_index is None else [parent_index]

    if not parent_indices:
        print(f"no parent branch found for {branch}")
        return

    for parent_position, parent_index in enumerate(parent_indices):
        if parent_position > 0:
            print()

        print_branch_parent_diff(rows[parent_index]["branch"], branch)


def print_nearest_parent_branch(branch):
    if not branch:
        sys.stderr.write("branch is required\n")
        sys.exit(2)

    rows = local_branch_rows()
    selected_index = next(
        (index for index, row in enumerate(rows) if row["branch"] == branch),
        None,
    )
    if selected_index is None:
        sys.stderr.write(f"branch not found: {branch}\n")
        sys.exit(1)

    parents_by_commit = commit_parent_map()
    parent_index = nearest_parent_indices(rows, parents_by_commit)[selected_index]
    if parent_index is None:
        sys.stderr.write(f"no parent branch found for {branch}\n")
        sys.exit(1)

    print(rows[parent_index]["branch"])


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


def children_by_parent(parent_index_sets):
    children = [set() for _ in parent_index_sets]
    for child_index, parent_indices in enumerate(parent_index_sets):
        for parent_index in parent_indices:
            children[parent_index].add(child_index)

    return children


def connected_components(parent_index_sets):
    children = children_by_parent(parent_index_sets)
    seen = set()
    components = []

    for start_index in range(len(parent_index_sets)):
        if start_index in seen:
            continue

        component = set()
        queue = collections.deque([start_index])
        seen.add(start_index)

        while queue:
            index = queue.popleft()
            component.add(index)

            neighbors = set(parent_index_sets[index]) | children[index]
            for neighbor_index in sorted(neighbors):
                if neighbor_index not in seen:
                    seen.add(neighbor_index)
                    queue.append(neighbor_index)

        components.append(component)

    return sorted(components, key=lambda component: min(component))


def branch_reverse_topological_order(component, parent_index_sets, children):
    remaining_child_counts = {
        index: len(children[index] & component)
        for index in component
    }
    ready = sorted(index for index, count in remaining_child_counts.items() if count == 0)
    rendered = set()
    order = []

    while ready:
        index = ready.pop(0)
        if index in rendered:
            continue

        rendered.add(index)
        order.append(index)

        for parent_index in parent_index_sets[index]:
            if parent_index not in component:
                continue

            remaining_child_counts[parent_index] -= 1
            if remaining_child_counts[parent_index] == 0:
                ready.append(parent_index)
                ready.sort()

    order.extend(index for index in sorted(component) if index not in rendered)
    return order


def branch_graph_node_symbol(parent_count, child_count):
    if parent_count > 1 and child_count > 1:
        return "●╋"
    if parent_count > 1:
        return "●┬"
    if child_count > 1:
        return "●┴"

    return "● "


def print_handmade_dag_rows(rows, parent_index_sets):
    children = children_by_parent(parent_index_sets)

    for component in connected_components(parent_index_sets):
        order = branch_reverse_topological_order(component, parent_index_sets, children)
        active_indices = []

        for index in order:
            if index not in active_indices:
                active_indices.append(index)

            lane = active_indices.index(index)
            parent_indices = [
                parent_index
                for parent_index in parent_index_sets[index]
                if parent_index in component
            ]
            child_count = len(children[index] & component)

            graph = "".join(
                branch_graph_node_symbol(len(parent_indices), child_count)
                if lane_index == lane
                else "│ "
                for lane_index in range(len(active_indices))
            ).rstrip()
            row = rows[index]

            print("\t".join([row["branch"], f"{graph} {visible_branch(rows, index)}", row["oid"], row["marker"]]))

            existing_indices = set(active_indices[:lane] + active_indices[lane + 1:])
            new_parent_indices = [
                parent_index
                for parent_index in parent_indices
                if parent_index not in existing_indices
            ]
            active_indices = active_indices[:lane] + new_parent_indices + active_indices[lane + 1:]


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
        if sys.argv[1] == "--preview":
            include_before_main = len(sys.argv) > 2 and sys.argv[2] == "--all"
            branch_argument_index = 3 if include_before_main else 2
            if len(sys.argv) <= branch_argument_index:
                return
            print_branch_ancestry_preview(sys.argv[branch_argument_index], include_before_main)
            return
        elif sys.argv[1] == "--diff-preview":
            preview_view = "tree"
            branch_argument_index = 2
            if len(sys.argv) > 2 and sys.argv[2] in {"--tree", "tree"}:
                branch_argument_index = 3
            elif len(sys.argv) > 2 and sys.argv[2] in {"--full-dag", "--dag", "full-dag", "dag"}:
                preview_view = "full-dag"
                branch_argument_index = 3

            if len(sys.argv) <= branch_argument_index:
                return

            print_branch_parent_diff_preview(sys.argv[branch_argument_index], preview_view)
            return
        elif sys.argv[1] in {"--nearest-parent", "--parent"}:
            if len(sys.argv) <= 2:
                sys.stderr.write("--nearest-parent requires a branch\n")
                sys.exit(2)

            print_nearest_parent_branch(sys.argv[2])
            return
        elif sys.argv[1] in {"--git-graph", "--y-graph", "git-graph", "y-graph"}:
            print_git_graph_rows()
            return
        elif sys.argv[1] in {"--handmade-dag", "--handmade", "handmade-dag", "handmade"}:
            view = "handmade-dag"
        elif sys.argv[1] in {"--full-dag", "--dag", "full-dag", "dag"}:
            view = "full-dag"
        elif sys.argv[1] not in {"--tree", "tree"}:
            sys.stderr.write(f"unknown view: {sys.argv[1]}\n")
            sys.exit(2)

    rows = read_branch_rows()
    if not rows:
        return

    parents_by_commit = commit_parent_map()
    if view == "handmade-dag":
        print_handmade_dag_rows(rows, nearest_parent_index_sets(rows, parents_by_commit))
    elif view == "full-dag":
        print_full_dag_rows(rows, nearest_parent_index_sets(rows, parents_by_commit))
    else:
        print_tree_rows(rows, nearest_parent_indices(rows, parents_by_commit))


if __name__ == "__main__":
    main()
