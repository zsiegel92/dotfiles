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

  if ! gcloud auth print-access-token >/dev/null 2>&1; then
    echo "gcloud authentication is missing or expired. Running: gcloud auth login"
    if ! gcloud auth login; then
      echo "gcloud auth login failed. Not restarting the Cloud SQL proxy."
      return 1
    fi
  fi

  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "Application Default Credentials are missing or expired. Running: gcloud auth application-default login"
    if ! gcloud auth application-default login; then
      echo "gcloud auth application-default login failed. Not restarting the Cloud SQL proxy."
      return 1
    fi
  fi

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Something is already listening on port ${port}:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN
    echo

    local listener_pid
    local listener_command
    local -a listener_pids
    listener_pids=("${(@f)$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null)}")

    for listener_pid in "${listener_pids[@]}"; do
      listener_command="$(ps -p "$listener_pid" -o command= 2>/dev/null)"
      if [[ "$listener_command" != *cloud-sql-proxy* ]]; then
        echo "Port ${port} is occupied by a process other than cloud-sql-proxy. Not restarting anything."
        return 1
      fi
    done

    echo "Stopping the existing Cloud SQL proxy on port ${port}."
    kill "${listener_pids[@]}" 2>/dev/null

    local attempts=0
    while lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && (( attempts < 20 )); do
      sleep 0.1
      (( attempts++ ))
    done

    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "The existing Cloud SQL proxy did not stop gracefully; killing it."
      listener_pids=("${(@f)$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null)}")
      for listener_pid in "${listener_pids[@]}"; do
        listener_command="$(ps -p "$listener_pid" -o command= 2>/dev/null)"
        if [[ "$listener_command" != *cloud-sql-proxy* ]]; then
          echo "Port ${port} is now occupied by a process other than cloud-sql-proxy. Not killing it."
          return 1
        fi
      done
      kill -9 "${listener_pids[@]}" 2>/dev/null
      sleep 0.1
    fi

    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Port ${port} is still occupied. Not starting another proxy."
      return 1
    fi
  fi

  echo "DOING \`${proxy_command}\`"

  cloud-sql-proxy "${project}:${region}:${db_instance}" \
    --address 127.0.0.1 \
    --port "$port" \
    >"$log_file" 2>&1 &

  local proxy_pid=$!
  sleep 1
  if ! kill -0 "$proxy_pid" 2>/dev/null; then
    echo "Cloud SQL proxy failed to start for ${db_instance} on port ${port}."
    echo "Logs:"
    cat "$log_file"
    return 1
  fi

  echo "$proxy_pid" > "$pid_file"

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

  echo "Started Cloud SQL proxy for ${db_instance} on port ${port}"
  echo "Proxy PID: ${proxy_pid}"
  echo "Logs: ${log_file}"
  echo "Exported ${env_var_name}"
}
