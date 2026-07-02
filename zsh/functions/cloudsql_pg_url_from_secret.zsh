cloudsql_pg_url_from_secret() {
  local db_instance="$1"
  local url_secret="$2"
  local port="$3"
  local env_var_name="$4"

  local project="kingfisher-nonprod-service"
  local region="us-east4"
  local log_file="/tmp/cloud-sql-proxy-${db_instance}-${port}.log"
  local pid_file="/tmp/cloud-sql-proxy-${db_instance}-${port}.pid"
  local proxy_command="cloud-sql-proxy ${project}:${region}:${db_instance} --address 127.0.0.1 --port ${port}"
  local proxy_already_running=0

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Something is already listening on port ${port}:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN
    echo
    if lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | while read -r listener_pid; do
      ps -p "$listener_pid" -o command=
    done | grep -q "cloud-sql-proxy"; then
      proxy_already_running=1
      echo "Cloud SQL proxy already running. Not starting another proxy."
    else
      echo "Not starting another proxy."
      return 1
    fi
  fi

  echo "DOING \`${proxy_command}\`"

  local proxy_pid=""
  if [[ "$proxy_already_running" -eq 0 ]]; then
    cloud-sql-proxy "${project}:${region}:${db_instance}" \
      --address 127.0.0.1 \
      --port "$port" \
      >"$log_file" 2>&1 &

    proxy_pid=$!
    sleep 1
    if ! kill -0 "$proxy_pid" 2>/dev/null; then
      echo "Cloud SQL proxy failed to start for ${db_instance} on port ${port}."
      echo "Logs:"
      cat "$log_file"
      return 1
    fi

    echo "$proxy_pid" > "$pid_file"
  fi

  echo "USING SECRET \`${url_secret}\`"
  echo "SETTING ENV VAR \`${env_var_name}\`"

  local rewritten_url
  rewritten_url="$(
    gcloud secrets versions access latest \
      --project="$project" \
      --secret="$url_secret" |
    python3 -c '
import sys, urllib.parse

port = sys.argv[1]
raw_url = sys.stdin.read().strip()
u = urllib.parse.urlsplit(raw_url)

netloc = f"{u.username}:{u.password}@127.0.0.1:{port}"

print(urllib.parse.urlunsplit((
    u.scheme,
    netloc,
    u.path,
    "sslmode=disable",
    "",
)))
' "$port"
  )"

  export "${env_var_name}=${rewritten_url}"

  if [[ "$proxy_already_running" -eq 0 ]]; then
    echo "Started Cloud SQL proxy for ${db_instance} on port ${port}"
    echo "Proxy PID: ${proxy_pid}"
    echo "Logs: ${log_file}"
  fi
  echo "Exported ${env_var_name}"
}
