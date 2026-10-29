#!/usr/bin/env bash
#
# mary.sh — единый менеджер локальных сервисов Mary Studio.
#
# Управляет ТОЛЬКО процессами, запущенными этим скриптом (PID в runtime/pids).
# Процессы, запущенные вручную или другим инструментом, не останавливаются.
#
#   ./mary.sh start [--follow] | stop | restart | status
#   ./mary.sh backend | frontend | comfy | worker
#   ./mary.sh logs [сервис] [--follow] | monitor | doctor | help
#
set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PID_DIR="$ROOT/runtime/pids"
LOG_DIR="$ROOT/runtime/logs"
COMFY_DIR="${MARY_COMFY_DIR:-$ROOT/runtime/ComfyUI}"
START_TIMEOUT="${MARY_START_TIMEOUT:-90}"
COMFY_TIMEOUT="${MARY_COMFY_TIMEOUT:-180}"
STOP_TIMEOUT="${MARY_STOP_TIMEOUT:-10}"

info() { printf '%s\n' "$*"; }
warn() { printf 'Внимание: %s\n' "$*" >&2; }
err() { printf 'Ошибка: %s\n' "$*" >&2; }
die() {
    err "$*"
    exit 1
}
have() { command -v "$1" > /dev/null 2>&1; }

# --- Описание сервисов -------------------------------------------------------
# svc_load заполняет глобальные SVC_* по имени сервиса.
svc_load() {
    SVC="$1"
    SVC_DIR=""
    SVC_PORT=""
    SVC_HEALTH=""
    SVC_MARK=""
    SVC_CHILD_MARK=""
    SVC_TIMEOUT="$START_TIMEOUT"
    SVC_TITLE=""
    SVC_URL=""
    case "$SVC" in
        backend)
            SVC_TITLE="Backend"
            SVC_DIR="$ROOT/backend"
            SVC_PORT="8000"
            SVC_HEALTH="http://127.0.0.1:8000/health"
            SVC_MARK="uvicorn app.main:app"
            SVC_URL="http://127.0.0.1:8000"
            ;;
        frontend)
            SVC_TITLE="Frontend"
            SVC_DIR="$ROOT/ui"
            SVC_PORT="5173"
            SVC_HEALTH="http://127.0.0.1:5173/"
            SVC_MARK="node_modules/.bin/vite"
            SVC_CHILD_MARK="$ROOT/ui/node_modules"
            SVC_URL="http://127.0.0.1:5173"
            ;;
        comfyui)
            SVC_TITLE="ComfyUI"
            SVC_DIR="$COMFY_DIR"
            SVC_PORT="8188"
            SVC_HEALTH="http://127.0.0.1:8188/system_stats"
            SVC_MARK="$COMFY_DIR/main.py"
            SVC_TIMEOUT="$COMFY_TIMEOUT"
            SVC_URL="http://127.0.0.1:8188"
            ;;
        worker)
            SVC_TITLE="Worker"
            SVC_MARK="worker/fake_worker.py"
            ;;
        *)
            return 1
            ;;
    esac
    SVC_PIDFILE="$PID_DIR/$SVC.pid"
    SVC_LOG="$LOG_DIR/$SVC.log"
    return 0
}

valid_svc() {
    case "$1" in
        backend | frontend | comfyui | worker) return 0 ;;
        *) return 1 ;;
    esac
}

# --- Процессы ----------------------------------------------------------------
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2> /dev/null; }

cmd_contains() {
    # -ww отключает усечение командной строки по ширине терминала.
    ps -ww -o command= -p "$1" 2> /dev/null | grep -qF "$2"
}

read_pid() {
    svc_load "$1" || return 1
    [ -f "$SVC_PIDFILE" ] || {
        printf ''
        return 0
    }
    raw="$(tr -d '[:space:]' < "$SVC_PIDFILE" 2> /dev/null)"
    case "$raw" in
        '' | *[!0-9]*) printf '' ;;
        *) printf '%s' "$raw" ;;
    esac
}

is_own_pid() {
    pid="$1"
    svc="$2"
    case "$pid" in
        '' | *[!0-9]*) return 1 ;;
    esac
    svc_load "$svc" || return 1
    pid_alive "$pid" || return 1
    cmd_contains "$pid" "$SVC_MARK" && return 0
    # Разовый сбой ps под нагрузкой не должен превращать свой процесс в чужой.
    sleep 0.2
    cmd_contains "$pid" "$SVC_MARK"
}

# own_pid: PID сервиса, только если он запущен mary.sh; иначе пусто.
own_pid() {
    svc="$1"
    pid="$(read_pid "$svc")"
    case "$pid" in
        '' | *[!0-9]*) printf ''; return 0 ;;
    esac
    if is_own_pid "$pid" "$svc"; then
        printf '%s' "$pid"
        return 0
    fi
    # PID-файл живого процесса не удаляем: иначе stop потеряет свой сервис.
    pid_alive "$pid" || rm -f "$PID_DIR/$svc.pid"
    printf ''
}

port_pids() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2> /dev/null | tr '\n' ' ' | sed 's/ $//'
}

port_busy() { [ -n "$(port_pids "$1")" ]; }

show_port_owner() {
    pids="$(port_pids "$1")"
    if [ -z "$pids" ]; then
        info "  порт $1 свободен"
        return 0
    fi
    for pid in $pids; do
        cmd="$(ps -o command= -p "$pid" 2> /dev/null | cut -c1-140)"
        info "  порт $1 занят PID $pid: ${cmd:-неизвестный процесс}"
    done
}

# --- HTTP --------------------------------------------------------------------
http_code() {
    [ -n "${1:-}" ] || {
        printf '000'
        return 0
    }
    curl -s -o /dev/null -m 2 --noproxy '*' -w '%{http_code}' "$1" 2> /dev/null || true
}

http_ok() {
    code="$(http_code "$1")"
    case "$code" in
        2* | 3*) return 0 ;;
        *) return 1 ;;
    esac
}

# --- PostgreSQL (внешний сервис, mary.sh им не управляет) -------------------
pg_target() {
    PG_HOST="127.0.0.1"
    PG_PORT="5432"
    url="${MARY_DATABASE_URL:-}"
    [ -n "$url" ] || return 0
    rest="${url#*://}"
    case "$rest" in
        *@*) rest="${rest#*@}" ;;
    esac
    hostport="${rest%%/*}"
    case "$hostport" in
        '') ;;
        \[*\]:*)
            PG_HOST="${hostport#[}"
            PG_HOST="${PG_HOST%%]*}"
            PG_PORT="${hostport##*:}"
            ;;
        *:*)
            PG_HOST="${hostport%:*}"
            PG_PORT="${hostport##*:}"
            ;;
        *) PG_HOST="$hostport" ;;
    esac
    [ -n "$PG_HOST" ] || PG_HOST="127.0.0.1"
}

pg_ready() {
    pg_target
    have pg_isready || return 1
    pg_isready -q -h "$PG_HOST" -p "$PG_PORT" 2> /dev/null
}

postgres_report() {
    if pg_ready; then
        info "Postgres: доступен (${PG_HOST}:${PG_PORT}) — управляется вне mary.sh"
    else
        warn "Postgres: недоступен (${PG_HOST}:${PG_PORT}) — запустите его отдельно"
    fi
}

# --- Состояние ---------------------------------------------------------------
service_state() {
    svc="$1"
    if [ "$svc" = "worker" ]; then
        printf 'not-configured'
        return 0
    fi
    svc_load "$svc" || {
        printf 'unknown'
        return 1
    }
    pid="$(own_pid "$svc")"
    if [ -n "$pid" ]; then
        code="$(http_code "$SVC_HEALTH")"
        case "$code" in
            2* | 3*) printf 'running-own' ;;
            5*) printf 'degraded-own' ;;
            *) printf 'starting-own' ;;
        esac
        return 0
    fi
    if http_ok "$SVC_HEALTH"; then
        printf 'external'
        return 0
    fi
    if [ -n "$SVC_PORT" ] && port_busy "$SVC_PORT"; then
        printf 'external-unhealthy'
        return 0
    fi
    printf 'stopped'
}

svc_label() {
    case "$(service_state "$1")" in
        running-own) printf 'RUNNING' ;;
        degraded-own) printf 'RUNNING (degraded)' ;;
        starting-own) printf 'STARTING' ;;
        external) printf 'RUNNING (external)' ;;
        external-unhealthy) printf 'EXTERNAL (no health)' ;;
        not-configured) printf 'NOT CONFIGURED' ;;
        *) printf 'STOPPED' ;;
    esac
}

print_status() {
    info "Mary Studio — Local Services"
    info ""
    printf '%-10s %-22s %s\n' "Backend" "$(svc_label backend)" "http://127.0.0.1:8000"
    printf '%-10s %-22s %s\n' "Frontend" "$(svc_label frontend)" "http://127.0.0.1:5173"
    printf '%-10s %-22s %s\n' "ComfyUI" "$(svc_label comfyui)" "http://127.0.0.1:8188"
    if pg_ready; then
        printf '%-10s %-22s %s\n' "Postgres" "READY" "${PG_HOST}:${PG_PORT}"
    else
        printf '%-10s %-22s %s\n' "Postgres" "UNAVAILABLE" "${PG_HOST}:${PG_PORT}"
    fi
    printf '%-10s %-22s %s\n' "Worker" "MANUAL" "worker/ltx_worker.py — запуск вручную"
    info ""
    info "Команды:"
    info "  ./mary.sh status"
    info "  ./mary.sh logs backend"
    info "  ./mary.sh stop"
}

# --- Запуск ------------------------------------------------------------------
tail_log() {
    svc_load "$1" || return 0
    if [ -f "$SVC_LOG" ]; then
        info "  последние строки $SVC_LOG:"
        tail -n 15 "$SVC_LOG" | sed 's/^/    /'
    fi
}

svc_prereqs_ok() {
    svc="$1"
    svc_load "$svc" || return 1
    case "$svc" in
        backend)
            [ -f "$ROOT/backend/app/main.py" ] || {
                err "не найден $ROOT/backend/app/main.py"
                return 1
            }
            [ -x "$ROOT/backend/.venv/bin/uvicorn" ] || {
                err "нет окружения backend: $ROOT/backend/.venv/bin/uvicorn (выполните: cd backend && uv sync)"
                return 1
            }
            ;;
        frontend)
            [ -f "$ROOT/ui/package.json" ] || {
                err "не найден $ROOT/ui/package.json"
                return 1
            }
            [ -x "$ROOT/ui/node_modules/.bin/vite" ] || {
                err "нет зависимостей UI: $ROOT/ui/node_modules (выполните: cd ui && npm install)"
                return 1
            }
            have node || {
                err "node не найден в PATH"
                return 1
            }
            ;;
        comfyui)
            [ -f "$COMFY_DIR/main.py" ] || {
                err "ComfyUI не найден: $COMFY_DIR (каталог можно задать через MARY_COMFY_DIR)"
                return 1
            }
            [ -x "$COMFY_DIR/.venv/bin/python" ] || {
                err "нет окружения ComfyUI: $COMFY_DIR/.venv/bin/python"
                return 1
            }
            [ -d "$COMFY_DIR/custom_nodes/comfyui-ltx2-mlx" ] || {
                err "нет custom node comfyui-ltx2-mlx в $COMFY_DIR/custom_nodes"
                return 1
            }
            ;;
    esac
    return 0
}

# exec_detached запускает команду в отдельной сессии (setsid), чтобы Ctrl+C
# в терминале — например, во время `./mary.sh start --follow` или `logs -f` —
# не попал в сервис. PID при этом не меняется (exec).
exec_detached() {
    if have perl; then
        exec perl -e 'use POSIX (); eval { POSIX::setsid() }; exec @ARGV or exit 127;' "$@"
    fi
    exec "$@"
}

# spawn_service запускает сервис в фоне и кладёт PID в SPAWNED_PID.
spawn_service() {
    svc="$1"
    svc_load "$svc" || return 1
    mkdir -p "$PID_DIR" "$LOG_DIR"
    (
        cd "$SVC_DIR" || exit 1
        # stdout/stderr идут в файл: без этого Python буферизует вывод блоками
        # и прогресс/сообщения появляются в логе с задержкой.
        export PYTHONUNBUFFERED=1
        case "$svc" in
            backend)
                exec_detached "$ROOT/backend/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000
                ;;
            frontend)
                exec_detached "$ROOT/ui/node_modules/.bin/vite" --host 127.0.0.1 --port 5173
                ;;
            comfyui)
                exec_detached "$COMFY_DIR/.venv/bin/python" "$COMFY_DIR/main.py" --listen 127.0.0.1 --port 8188 --disable-auto-launch
                ;;
            *)
                exit 1
                ;;
        esac
    ) >> "$SVC_LOG" 2>&1 &
    SPAWNED_PID=$!
    printf '%s\n' "$SPAWNED_PID" > "$SVC_PIDFILE"
    disown 2> /dev/null || true
    return 0
}

wait_ready() {
    svc="$1"
    pid="$2"
    limit="$3"
    svc_load "$svc" || return 1
    waited=0
    while [ "$waited" -lt "$limit" ]; do
        if ! pid_alive "$pid"; then
            err "$SVC_TITLE: процесс завершился при старте"
            tail_log "$svc"
            return 1
        fi
        if http_ok "$SVC_HEALTH"; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
        if [ $((waited % 15)) -eq 0 ]; then
            info "  ... $SVC_TITLE: ожидание готовности (${waited}s из ${limit}s)"
        fi
    done
    err "$SVC_TITLE: не готов за ${limit}s ($SVC_HEALTH)"
    tail_log "$svc"
    return 1
}

start_one() {
    svc="$1"
    if [ "$svc" = "worker" ]; then
        worker_report
        return 1
    fi
    svc_load "$svc" || {
        err "неизвестный сервис: $svc"
        return 1
    }
    state="$(service_state "$svc")"
    case "$state" in
        running-own)
            info "$SVC_TITLE: уже запущен этим менеджером (PID $(own_pid "$svc"))"
            return 0
            ;;
        degraded-own)
            info "$SVC_TITLE: процесс запущен (PID $(own_pid "$svc")), но health отдаёт $(http_code "$SVC_HEALTH") — проверьте PostgreSQL"
            return 0
            ;;
        starting-own)
            info "$SVC_TITLE: уже запускается, ждём готовности..."
            wait_ready "$svc" "$(own_pid "$svc")" "$SVC_TIMEOUT" && return 0
            return 1
            ;;
        external)
            info "$SVC_TITLE: уже работает вне mary.sh (порт $SVC_PORT) — не запускаю"
            return 0
            ;;
        external-unhealthy)
            err "$SVC_TITLE: порт $SVC_PORT занят, но $SVC_HEALTH не отвечает"
            show_port_owner "$SVC_PORT"
            return 1
            ;;
    esac

    if ! svc_prereqs_ok "$svc"; then
        return 1
    fi
    info "$SVC_TITLE: запуск..."
    if ! spawn_service "$svc"; then
        err "$SVC_TITLE: не удалось запустить процесс"
        return 1
    fi
    pid="$SPAWNED_PID"
    svc_load "$svc"
    if wait_ready "$svc" "$pid" "$SVC_TIMEOUT"; then
        info "$SVC_TITLE: готов — $SVC_URL"
        return 0
    fi
    stop_one "$svc"
    return 1
}

# --- Остановка ---------------------------------------------------------------
stop_one() {
    svc="$1"
    if [ "$svc" = "worker" ]; then
        info "Worker: не управляется mary.sh"
        return 0
    fi
    svc_load "$svc" || {
        err "неизвестный сервис: $svc"
        return 1
    }
    pid="$(own_pid "$svc")"
    case "$pid" in
        '' | *[!0-9]*) pid="" ;;
    esac
    if [ -z "$pid" ]; then
        state="$(service_state "$svc")"
        case "$state" in
            external | external-unhealthy)
                info "$SVC_TITLE: запущен вне mary.sh — не останавливаю"
                ;;
            *) info "$SVC_TITLE: не запущен" ;;
        esac
        return 0
    fi

    info "$SVC_TITLE: остановка (PID $pid)..."
    kids="$(pgrep -P "$pid" 2> /dev/null | tr '\n' ' ')"
    kill -TERM "$pid" 2> /dev/null || true
    waited=0
    while pid_alive "$pid" && [ "$waited" -lt "$STOP_TIMEOUT" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if pid_alive "$pid"; then
        if is_own_pid "$pid" "$svc"; then
            warn "$SVC_TITLE: не завершился за ${STOP_TIMEOUT}s — SIGKILL"
            kill -KILL "$pid" 2> /dev/null || true
        else
            err "$SVC_TITLE: PID $pid больше не принадлежит сервису — не завершаю"
        fi
    fi

    if [ -n "$SVC_CHILD_MARK" ]; then
        for kid in $kids; do
            pid_alive "$kid" || continue
            cmd_contains "$kid" "$SVC_CHILD_MARK" || continue
            kill -TERM "$kid" 2> /dev/null || true
            n=0
            while pid_alive "$kid" && [ "$n" -lt 5 ]; do
                sleep 1
                n=$((n + 1))
            done
            pid_alive "$kid" && kill -KILL "$kid" 2> /dev/null || true
        done
    fi

    rm -f "$SVC_PIDFILE"
    info "$SVC_TITLE: остановлен"
    return 0
}

# --- Worker ------------------------------------------------------------------
worker_report() {
    info "Worker: MANUAL"
    info "  Реальный LTX-воркер: worker/ltx_worker.py (WP-N3/N4), тестовый — worker/fake_worker.py."
    info "  mary.sh намеренно не запускает тяжёлые рендеры сам. Ручной запуск одной job:"
    info '    backend/.venv/bin/python worker/ltx_worker.py --once --token "$MARY_WORKER_TOKEN"'
    info '    backend/.venv/bin/python worker/ltx_worker.py --series-run <run_id> --token "$MARY_WORKER_TOKEN"'
    info '    backend/.venv/bin/python worker/fake_worker.py --once --token "$MARY_WORKER_TOKEN"'
}

# --- Команды -----------------------------------------------------------------
cmd_start() {
    follow=0
    targets=""
    for arg in "$@"; do
        case "$arg" in
            -f | --follow) follow=1 ;;
            *) targets="$targets $arg" ;;
        esac
    done
    targets="${targets# }"
    [ -n "$targets" ] || targets="backend frontend comfyui"
    info "Mary Studio — запуск"
    postgres_report
    failed=""
    for s in $targets; do
        valid_svc "$s" || {
            err "неизвестный сервис: $s"
            failed="$failed $s"
            continue
        }
        start_one "$s" || failed="$failed $s"
    done
    info ""
    print_status
    if [ -n "$failed" ]; then
        err "не удалось запустить:$failed"
        return 1
    fi
    info ""
    info "Worker автоматически не запускается: ./mary.sh worker — подробности."
    if [ "$follow" -eq 1 ]; then
        info ""
        info "Открываю monitor (Ctrl+C — выход из монитора, сервисы продолжат работу)."
        sleep 1
        cmd_monitor
    fi
    return 0
}

cmd_stop() {
    if [ $# -gt 0 ]; then
        targets="$*"
    else
        targets="backend frontend comfyui"
    fi
    failed=""
    for s in $targets; do
        valid_svc "$s" || {
            err "неизвестный сервис: $s"
            failed="1"
            continue
        }
        stop_one "$s" || failed="1"
    done
    postgres_report
    [ -z "$failed" ] || return 1
    return 0
}

cmd_restart() {
    cmd_stop "$@" || true
    info ""
    cmd_start "$@"
}

normalize_svc() {
    case "$1" in
        comfy) printf 'comfyui' ;;
        *) printf '%s' "$1" ;;
    esac
}

cmd_logs() {
    follow=0
    svc=""
    for arg in "$@"; do
        case "$arg" in
            -f | --follow) follow=1 ;;
            -*) die "неизвестный флаг: $arg" ;;
            *) svc="$arg" ;;
        esac
    done
    if [ -n "$svc" ]; then
        svc="$(normalize_svc "$svc")"
        valid_svc "$svc" || die "неизвестный сервис: $svc"
        [ "$svc" = "worker" ] && die "worker не управляется mary.sh"
        svc_load "$svc"
        [ -f "$SVC_LOG" ] || die "лог не найден: $SVC_LOG"
        # Ctrl+C завершает только tail: сервис запущен в отдельной сессии.
        tail -n 100 -f "$SVC_LOG"
        return 0
    fi
    if [ "$follow" -eq 1 ]; then
        files=""
        for s in backend frontend comfyui; do
            svc_load "$s"
            [ -f "$SVC_LOG" ] && files="$files $SVC_LOG"
        done
        [ -n "$files" ] || die "логов нет: сервисы ещё не запускались"
        # shellcheck disable=SC2086
        tail -n 20 -f $files
        return 0
    fi
    for s in backend frontend comfyui; do
        svc_load "$s"
        info "== $s: $SVC_LOG =="
        if [ -f "$SVC_LOG" ]; then
            tail -n 30 "$SVC_LOG"
        else
            info "  (лога нет)"
        fi
        info ""
    done
}

# --- Monitor -----------------------------------------------------------------
# Источники (без собственного реестра статусов):
#   - health endpoints сервисов (как в status);
#   - GET /api/jobs?limit=10 — состояние render job;
#   - GET /queue ComfyUI — prompt_id, очередь, create_time;
#   - runtime/logs/comfyui.log — этап, N/M (если публикует нода), ошибки, сообщения.
MONITOR_INTERVAL="${MARY_MONITOR_INTERVAL:-2}"

mon_styles() {
    if [ -t 1 ]; then
        C_RESET=$'\033[0m'
        C_DIM=$'\033[2m'
        C_OK=$'\033[32m'
        C_WARN=$'\033[33m'
        C_BAD=$'\033[31m'
    else
        C_RESET=""
        C_DIM=""
        C_OK=""
        C_WARN=""
        C_BAD=""
    fi
}

mon_color_state() {
    state="$(service_state "$1")"
    label="$(svc_label "$1")"
    case "$state" in
        running-own | external) printf '%s%s%s' "$C_OK" "$label" "$C_RESET" ;;
        starting-own | degraded-own) printf '%s%s%s' "$C_WARN" "$label" "$C_RESET" ;;
        not-configured) printf '%s%s%s' "$C_DIM" "$label" "$C_RESET" ;;
        *) printf '%s%s%s' "$C_BAD" "$label" "$C_RESET" ;;
    esac
}

mon_short_id() {
    case "${1:-}" in
        '') printf '-' ;;
        *) printf '%s' "${1%%-*}" ;;
    esac
}

fmt_elapsed() {
    raw="${1:-}"
    case "$raw" in
        '' | *[!0-9.]*) printf '?'; return 0 ;;
    esac
    secs="${raw%.*}"
    case "$secs" in
        '' | *[!0-9]*) printf '?'; return 0 ;;
    esac
    [ "$secs" -lt 0 ] && secs=0
    printf '%02d:%02d:%02d' $((secs / 3600)) $(((secs % 3600) / 60)) $((secs % 60))
}

# comfy_log_since_prompt — строки лога после последнего "got prompt".
comfy_log_since_prompt() {
    [ -f "$LOG_DIR/comfyui.log" ] || return 0
    tail -n 400 "$LOG_DIR/comfyui.log" 2> /dev/null | awk '
        /got prompt/ { buf = "" }
        { buf = buf $0 "\n" }
        END { printf "%s", buf }'
}

# mon_error — текущая ошибка prompt'а. Ошибка считается текущей, только если
# после неё в логе не было "Prompt executed in" (иначе это хвост прошлого прогона).
mon_error() {
    slice="$1"
    for marker in '!!! Exception during processing' 'Processing interrupted'; do
        case "$slice" in
            *"$marker"*) ;;
            *) continue ;;
        esac
        after="${slice##*"$marker"}"
        case "$after" in
            *'Prompt executed in'*) continue ;;
        esac
        printf '%s' "$marker"
        return 0
    done
    return 0
}

mon_stage() {
    slice="$1"
    prompt="$2"
    err="$(mon_error "$slice")"
    if [ -n "$err" ]; then
        case "$err" in
            *interrupted*) printf 'прервано (ComfyUI: processing interrupted)' ;;
            *) printf 'ошибка (ComfyUI: exception during processing)' ;;
        esac
        return 0
    fi
    if [ -n "$prompt" ]; then
        case "$slice" in
            *'Prompt executed in'*) printf 'завершение' ;;
            *'muxing'*'done in'*) printf 'сохранение' ;;
            *'Decoding'*) printf 'декодирование' ;;
            *'Denoising:'*) printf 'генерация' ;;
            *'Requested to load'*)
                case "$slice" in
                    *'loaded completely'*) printf 'загрузка модели (веса загружены)' ;;
                    *) printf 'загрузка модели' ;;
                esac
                ;;
            *'got prompt'*) printf 'подготовка' ;;
            *) printf 'генерация' ;;
        esac
        return 0
    fi
    sec="$(printf '%s' "$slice" | grep 'Prompt executed in' | tail -n 1 | sed -n 's/.*Prompt executed in \([0-9][0-9:.]*\).*/\1/p')"
    if [ -n "$sec" ]; then
        printf 'завершение (последний prompt, %s)' "$sec"
        return 0
    fi
    printf 'неизвестен (нет активного prompt)'
}

# Прогресс N/M — только из прогресс-бара текущего prompt'а (срез после "got prompt").
# Строки прогресса разделены \r, поэтому tr обязателен.
mon_progress() {
    slice="$1"
    prompt="$2"
    if [ ! -f "$LOG_DIR/comfyui.log" ]; then
        printf 'неизвестен (лога нет)'
        return 0
    fi
    if [ -z "$prompt" ]; then
        case "$slice" in
            *'Prompt executed in'*) printf 'неизвестен (prompt завершён)' ;;
            *) printf 'неизвестен (нет активного prompt)' ;;
        esac
        return 0
    fi
    line="$(printf '%s' "$slice" | tr '\r' '\n' | grep -E '[0-9]+/[0-9]+' | tail -n 1)"
    nm="$(printf '%s' "$line" | grep -oE '[0-9]+/[0-9]+' | tail -n 1)"
    if [ -z "$nm" ]; then
        printf 'неизвестен (нода не публикует N/M)'
        return 0
    fi
    label="$(printf '%s' "$line" | sed -n 's/^\([^:]*\): *[0-9][0-9]*%|.*/\1/p' | cut -c1-40)"
    if [ -n "$label" ]; then
        printf '%s %s (из лога ComfyUI)' "$label" "$nm"
    else
        printf '%s (из лога ComfyUI)' "$nm"
    fi
}

mon_messages() {
    shown=0
    if [ -f "$LOG_DIR/comfyui.log" ]; then
        out="$(tail -n 120 "$LOG_DIR/comfyui.log" 2> /dev/null | tr '\r' '\n' | grep -v '^[[:space:]]*$' | tail -n 3 | cut -c1-110 | sed 's/^/  comfyui  /')"
        [ -n "$out" ] && {
            printf '%s\n' "$out"
            shown=1
        }
    fi
    if [ -f "$LOG_DIR/backend.log" ]; then
        out="$(tail -n 40 "$LOG_DIR/backend.log" 2> /dev/null | tr '\r' '\n' | grep -v '^[[:space:]]*$' | tail -n 2 | cut -c1-110 | sed 's/^/  backend  /')"
        [ -n "$out" ] && {
            printf '%s\n' "$out"
            shown=1
        }
    fi
    [ "$shown" -eq 1 ] || printf '  (нет данных)\n'
}

mon_jobs_block() {
    if ! http_ok 'http://127.0.0.1:8000/health'; then
        printf 'Нет данных: backend недоступен — состояние render job неизвестно.\n'
        return 0
    fi
    if ! have jq; then
        printf 'Нет данных: jq не найден — состояние render job недоступно.\n'
        return 0
    fi
    jobs_json="$(curl -s -m 2 --noproxy '*' 'http://127.0.0.1:8000/api/jobs?limit=10' 2> /dev/null)"
    # created_at приходит в ISO 8601 с любым смещением (+01:00, Z) — считаем epoch.
    jobs_jq='def ts2epoch:
        sub("\\.[0-9]+"; "") as $s
        | if ($s | endswith("Z")) then ($s | fromdateiso8601)
          else ($s | capture("^(?<d>[0-9T:-]+)(?<sign>[+-])(?<h>[0-9]{2}):(?<m>[0-9]{2})$")) as $p
          | ($p.d + "Z" | fromdateiso8601)
            - (if $p.sign == "-" then -1 else 1 end) * ((($p.h | tonumber) * 3600) + (($p.m | tonumber) * 60))
          end;
      [.[] | select(.status=="pending" or .status=="leased" or .status=="running" or .status=="retry_wait" or .status=="cancel_requested" or .status=="lease_expired")]
      | first // empty
      | [.id, .status, (.attempts|tostring), (.max_attempts|tostring), (.error_code // "-"), (.lease_owner // "-"),
         (try ((now - (.created_at | ts2epoch)) | floor | tostring) catch "")] | @tsv'
    active="$(printf '%s' "$jobs_json" | jq -r "$jobs_jq" 2> /dev/null)"
    if [ -n "$active" ]; then
        IFS=$'\t' read -r job_id job_status job_att job_max job_err job_owner job_age <<< "$active"
        printf 'Job:       %s  render_video  %s  попытка %s/%s  прошло %s  worker %s\n' \
            "$(mon_short_id "$job_id")" "$job_status" "$job_att" "$job_max" "$(fmt_elapsed "$job_age")" "$job_owner"
        if [ "$job_err" != "-" ]; then
            printf 'Ошибка:    job %s — %s\n' "$(mon_short_id "$job_id")" "$job_err"
        fi
        return 0
    fi
    last="$(printf '%s' "$jobs_json" | jq -r '[.[] | select(.status=="failed" or .status=="lease_expired")] | first // empty | [.id, .status, (.error_code // "-")] | @tsv' 2> /dev/null)"
    if [ -n "$last" ]; then
        IFS=$'\t' read -r last_id last_status last_err <<< "$last"
        printf 'Job:       нет активного; последний сбой %s (%s, %s)\n' \
            "$(mon_short_id "$last_id")" "$last_status" "$last_err"
        return 0
    fi
    printf 'Job:       нет активного render job\n'
}

mon_comfy_block() {
    queue_json=""
    if have jq; then
        queue_json="$(curl -s -m 2 --noproxy '*' 'http://127.0.0.1:8188/queue' 2> /dev/null)"
    fi
    if [ -z "$queue_json" ]; then
        printf 'ComfyUI:   нет данных (сервис не запущен или /queue недоступен)\n'
        printf 'Этап:      нет данных\n'
        printf 'Прогресс:  нет данных\n'
        return 0
    fi
    prompt_id="$(printf '%s' "$queue_json" | jq -r '.queue_running[0][1] // empty' 2> /dev/null)"
    pending="$(printf '%s' "$queue_json" | jq -r '.queue_pending | length' 2> /dev/null)"
    prompt_age="$(printf '%s' "$queue_json" | jq -r '(.queue_running[0][3].create_time // empty) | if . == "" then empty else (now - (. / 1000)) end' 2> /dev/null)"
    if [ -n "$prompt_id" ]; then
        printf 'ComfyUI:   prompt %s  в очереди %s  прошло %s\n' \
            "$(mon_short_id "$prompt_id")" "${pending:-?}" "$(fmt_elapsed "$prompt_age")"
    else
        printf 'ComfyUI:   очередь пуста (prompt не выполняется)\n'
    fi
    printf 'Этап:      %s\n' "$(mon_stage "$(comfy_log_since_prompt)" "$prompt_id")"
    printf 'Прогресс:  %s\n' "$(mon_progress "$(comfy_log_since_prompt)" "$prompt_id")"
}

mon_frame() {
    printf '%sMary Studio — monitor%s   %s   интервал %ss   Ctrl+C — выход\n' \
        "$C_DIM" "$C_RESET" "$(date '+%H:%M:%S')" "$MONITOR_INTERVAL"
    printf '%s────────────────────────────────────────────────────────────────────────%s\n' "$C_DIM" "$C_RESET"

    printf 'Сервисы:   Backend %s   Frontend %s\n' "$(mon_color_state backend)" "$(mon_color_state frontend)"
    printf '           ComfyUI %s   Worker %s\n' "$(mon_color_state comfyui)" "$(mon_color_state worker)"
    if pg_ready; then
        printf 'Postgres:  %sREADY%s %s:%s\n' "$C_OK" "$C_RESET" "$PG_HOST" "$PG_PORT"
    else
        printf 'Postgres:  %sUNAVAILABLE%s %s:%s\n' "$C_BAD" "$C_RESET" "$PG_HOST" "$PG_PORT"
    fi
    printf '\n'

    mon_jobs_block
    mon_comfy_block
    printf '\nПоследние сообщения:\n'
    mon_messages
    printf '\n%sИсточники: health endpoints, GET /api/jobs, GET /queue, runtime/logs/%s\n' "$C_DIM" "$C_RESET"
}

mon_cleanup() {
    printf '%s' "$C_RESET"
    printf '\033[?25h'
    trap - EXIT INT TERM
    exit 0
}

cmd_monitor() {
    once=0
    for arg in "$@"; do
        case "$arg" in
            --once) once=1 ;;
            *) die "неизвестный аргумент monitor: $arg" ;;
        esac
    done
    case "$MONITOR_INTERVAL" in
        '' | *[!0-9]*) MONITOR_INTERVAL=2 ;;
    esac
    [ "$MONITOR_INTERVAL" -gt 0 ] || MONITOR_INTERVAL=2
    mon_styles
    if [ "$once" -eq 1 ]; then
        mon_frame
        return 0
    fi
    trap 'mon_cleanup' EXIT INT TERM
    printf '\033[?25l\033[2J'
    while :; do
        printf '\033[H'
        mon_frame
        printf '\033[J'
        sleep "$MONITOR_INTERVAL"
    done
}

# --- Doctor ------------------------------------------------------------------
FAILS=0
ok() { printf '  [OK]   %s\n' "$*"; }
bad() {
    printf '  [FAIL] %s\n' "$*"
    FAILS=$((FAILS + 1))
}
wr() { printf '  [WARN] %s\n' "$*"; }

python_check() {
    py="$1"
    label="$2"
    imports="$3"
    if [ ! -x "$py" ]; then
        bad "$label: нет интерпретатора $py"
        return 0
    fi
    ver="$("$py" --version 2>&1)"
    if [ -n "$imports" ] && ! "$py" -c "import $imports" > /dev/null 2>&1; then
        bad "$label: $ver, не импортируются: $imports"
    else
        ok "$label: $ver, импорты OK${imports:+ ($imports)}"
    fi
}

cmd_doctor() {
    FAILS=0
    info "Mary Studio — doctor"
    info ""
    info "Система:"
    ok "$(sw_vers -productName 2> /dev/null || echo macOS) $(sw_vers -productVersion 2> /dev/null || echo '?'), $(uname -m)"

    info ""
    info "Инструменты:"
    for t in python3 uv node npm ffmpeg curl lsof pg_isready; do
        if have "$t"; then
            ok "$t: $(command -v "$t")"
        else
            bad "$t не найден в PATH"
        fi
    done

    info ""
    info "Каталоги:"
    if [ -f "$ROOT/backend/app/main.py" ]; then
        ok "backend: $ROOT/backend"
    else
        bad "не найден backend/app/main.py"
    fi
    if [ -f "$ROOT/ui/package.json" ]; then
        ok "UI: $ROOT/ui"
    else
        bad "не найден ui/package.json"
    fi
    if [ -f "$COMFY_DIR/main.py" ]; then
        ok "ComfyUI: $COMFY_DIR"
    else
        bad "ComfyUI не найден: $COMFY_DIR (задайте MARY_COMFY_DIR)"
    fi
    if [ -d "$COMFY_DIR/custom_nodes/comfyui-ltx2-mlx" ]; then
        ok "custom node comfyui-ltx2-mlx"
    else
        bad "нет custom node comfyui-ltx2-mlx"
    fi
    if [ -f "$ROOT/comfyui-workflows/ltx23_mlx_q4_i2v.api.json" ]; then
        ok "workflow LTX I2V: comfyui-workflows/ltx23_mlx_q4_i2v.api.json"
    else
        bad "нет comfyui-workflows/ltx23_mlx_q4_i2v.api.json"
    fi

    info ""
    info "Python-окружения (каждое проверяется своим интерпретатором):"
    python_check "$ROOT/.venv/bin/python" "legacy (.venv)" "httpx, dotenv"
    python_check "$ROOT/backend/.venv/bin/python" "backend (uv)" "fastapi, sqlalchemy, alembic, psycopg, uvicorn"
    python_check "$COMFY_DIR/.venv/bin/python" "ComfyUI" "torch, mlx"

    info ""
    info "PostgreSQL:"
    pg_target
    if pg_ready; then
        ok "доступен ${PG_HOST}:${PG_PORT}"
    else
        bad "недоступен ${PG_HOST}:${PG_PORT} — запустите PostgreSQL 16"
    fi
    if [ -n "${MARY_DATABASE_URL:-}" ]; then
        info "  MARY_DATABASE_URL задан в окружении (значение не выводится)"
    else
        info "  MARY_DATABASE_URL не задан — backend использует дефолт localhost:5432/mary_studio"
    fi

    info ""
    info "Конфигурация:"
    if [ -f "$ROOT/.env" ]; then
        ok "корневой .env присутствует (содержимое не читается)"
    else
        wr "корневой .env отсутствует — нужен legacy-пайплайну: cp .env.example .env"
    fi
    if [ -f "$ROOT/backend/.env" ]; then
        wr "backend/.env существует, но backend его не читает (только переменные окружения MARY_*)"
    else
        info "  backend/.env отсутствует: backend читает только переменные окружения MARY_*"
    fi
    if [ -n "${MARY_WORKER_TOKEN:-}" ]; then
        ok "MARY_WORKER_TOKEN задан в окружении"
    else
        wr "MARY_WORKER_TOKEN не задан — worker API и worker недоступны"
    fi

    info ""
    info "Порты:"
    for p in 5173 8000 8188; do
        pids="$(port_pids "$p")"
        if [ -z "$pids" ]; then
            ok "порт $p свободен"
        else
            for pid in $pids; do
                cmd="$(ps -o command= -p "$pid" 2> /dev/null | cut -c1-120)"
                ok "порт $p занят PID $pid: ${cmd:-неизвестный процесс}"
            done
        fi
    done

    info ""
    if [ "$FAILS" -gt 0 ]; then
        err "проблем: $FAILS — исправьте пункты [FAIL]"
        return 1
    fi
    info "Критичных проблем не найдено."
    return 0
}

cmd_help() {
    cat <<'EOF'
Mary Studio — управление локальными сервисами

Использование:
  ./mary.sh start [--follow] [сервис...]
                                  запустить backend, frontend, ComfyUI;
                                  --follow дополнительно открывает monitor
  ./mary.sh stop [сервис...]      остановить только процессы mary.sh
  ./mary.sh restart [сервис...]   перезапустить
  ./mary.sh status                состояние сервисов
  ./mary.sh backend               запустить только FastAPI (:8000)
  ./mary.sh frontend              запустить только Vite (:5173)
  ./mary.sh comfy                 запустить только ComfyUI (:8188)
  ./mary.sh worker                состояние worker и как запустить вручную
  ./mary.sh logs [сервис] [-f]    логи; без аргумента — последние строки всех,
                                  -f/--follow — следить за выводом (Ctrl+C — выход)
  ./mary.sh monitor [--once]      живой монитор: сервисы, job, этап, прогресс
  ./mary.sh doctor                проверка окружений, портов и зависимостей
  ./mary.sh help                  эта справка

Сервисы: backend, frontend, comfyui (алиас comfy), worker.

Процессы, запущенные вручную, показываются как external и не останавливаются.
PostgreSQL и worker mary.sh не запускает — только проверяет доступность.
PID-файлы: runtime/pids/, логи: runtime/logs/ (каталог вне Git).

Monitor показывает только данные из существующих источников: health endpoints,
GET /api/jobs, GET /queue ComfyUI и runtime/logs/*.log. Если N/M шагов
не публикуется — выводится «Прогресс: неизвестен».
EOF
}

# --- Диспетчер ---------------------------------------------------------------
cmd="${1:-help}"
if [ $# -gt 0 ]; then
    shift
fi

case "$cmd" in
    start) cmd_start "$@" ;;
    stop) cmd_stop "$@" ;;
    restart) cmd_restart "$@" ;;
    status) print_status ;;
    backend | frontend | comfy)
        if [ "$cmd" = "comfy" ]; then
            start_one comfyui
        else
            start_one "$cmd"
        fi
        ;;
    worker) worker_report ;;
    logs) cmd_logs "$@" ;;
    monitor) cmd_monitor "$@" ;;
    doctor) cmd_doctor ;;
    help | -h | --help) cmd_help ;;
    *)
        err "неизвестная команда: $cmd"
        info ""
        cmd_help
        exit 2
        ;;
esac
exit $?
