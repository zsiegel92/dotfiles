# Enter a selected worktree in the current shell. The executable provides the fzf UI and actions.
worktree-manager() {
  if [[ ${1:-} == --* ]]; then
    command worktree-manager "$@"
    return
  fi

  local selected_worktree
  selected_worktree=$(command worktree-manager --select "$@") || return
  [ -n "$selected_worktree" ] && cd -- "$selected_worktree"
}

wt() {
  worktree-manager "$@"
}
