import http.server
import json
import threading
import logging

logger = logging.getLogger(__name__)

class MockLlamaServerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging to stdout to keep test logs clean
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(body)
            
            # Log the request payload for assertions in tests
            self.server.request_log.append(payload)
            
            # Determine the response
            if self.server.response_queue:
                response_content = self.server.response_queue.pop(0)
            else:
                response_content = {
                    "note": "Default note",
                    "thought": "Default thought",
                    "tool_call": {
                        "tool_name": "terminate",
                        "status": "success",
                        "reason": "Default terminate from mock server"
                    }
                }
            
            # If response_content is already a string, use it. Otherwise, dump to JSON.
            content_str = response_content if isinstance(response_content, str) else json.dumps(response_content)
            
            response_payload = {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 123456789,
                "model": "mock-holo3",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content_str
                        },
                        "finish_reason": "stop"
                    }
                ]
            }
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode())
        else:
            self.send_response(404)
            self.end_headers()

class MockLlamaServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.request_log = []
        self.response_queue = []

class MockLlamaServerController:
    def __init__(self, port=58089):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        self.server = MockLlamaServer(("127.0.0.1", self.port), MockLlamaServerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Mock Llama Server started on port {self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        logger.info("Mock Llama Server stopped")

    def queue_response(self, response_dict_or_str):
        if self.server:
            self.server.response_queue.append(response_dict_or_str)

    def get_requests(self):
        if self.server:
            return self.server.request_log
        return []

    def clear(self):
        if self.server:
            self.server.request_log.clear()
            self.server.response_queue.clear()

_shared_server_controller = None

def get_shared_server():
    global _shared_server_controller
    if _shared_server_controller is None:
        _shared_server_controller = MockLlamaServerController(port=58089)
        _shared_server_controller.start()
    return _shared_server_controller

def stop_shared_server():
    global _shared_server_controller
    if _shared_server_controller is not None:
        _shared_server_controller.stop()
        _shared_server_controller = None
