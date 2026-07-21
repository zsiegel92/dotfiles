# Select a Kubernetes config and export it in the current shell.
set_kubeconfig() {
  local kube_dir="$HOME/.kube"
  local selected_file
  local preview_command
  local open_command

  if ! command -v fzf >/dev/null 2>&1; then
    echo "set_kubeconfig: fzf is required" >&2
    return 1
  fi

  if [[ ! -d "$kube_dir" ]]; then
    echo "set_kubeconfig: directory not found: $kube_dir" >&2
    return 1
  fi

  preview_command='KUBECONFIG="$HOME/.kube/"{}; export KUBECONFIG; printf "export KUBECONFIG=\$HOME/.kube/%s\\n\\n" {}; printf "kubectl --help\\n\\n"; printf "kubectl get pods -A\\n\\n"; kubectl get pods -A; printf "\\n\\nkubectl auth can-i create services -n runa-kingfisher\\n\\n"; kubectl auth can-i create services -n runa-kingfisher; printf "\\n\\nKubeconfig: %s\\n\\n" "$KUBECONFIG"; bat --color=always --paging=never --style=plain --wrap=character ${FZF_PREVIEW_COLUMNS:+--terminal-width="$FZF_PREVIEW_COLUMNS"} -- "$KUBECONFIG"'
  open_command="code --reuse-window -- ${(q)kube_dir}/{}"

  selected_file=$(find "$kube_dir" -maxdepth 1 -type f -exec basename {} \; | sort | fzf \
    --prompt='kubeconfig> ' \
    --header='enter: set KUBECONFIG · ctrl-o: open in VS Code' \
    --no-mouse \
    --preview-window='right,60%,<100(down,50%,border-top)' \
    --bind='pgup:preview-page-up,pgdn:preview-page-down' \
    --bind="ctrl-o:execute-silent($open_command)" \
    --preview="$preview_command") || return

  [[ -n "$selected_file" ]] || return
  export KUBECONFIG="$kube_dir/$selected_file"
}
