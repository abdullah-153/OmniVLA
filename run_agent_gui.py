import sys
import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"

# Import everything from the new location to keep backward compatibility
from cogniagent.gui.app import (
    agent_status,
    server_process,
    planner_process,
    active_planner_gpu,
    active_vla_max_gpu,
    electron_process,
    running_thread,
    stop_requested,
    hitl_event,
    hitl_response,
    recording_active,
    recording_writer,
    recording_loop,
    WebLogHandler,
    web_log_handler,
    DesktopOverlay,
    start_planner_server,
    run_planner_chat,
    start_llama_server,
    execute_agent_task,
    parse_server_log_for_optimizations,
    check_vram_limit,
    TextHandler,
    OmniVLA_GUI,
    sync_chats_on_startup,
    main,
    HTML_CONTENT
)

if __name__ == "__main__":
    main()
