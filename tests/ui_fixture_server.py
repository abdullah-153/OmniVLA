import sys, tempfile, os, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests.conftest
from http.server import ThreadingHTTPServer
from cogniagent.gui import server, app
from cogniagent.memory import user_profile
root = tempfile.TemporaryDirectory(prefix='omnivla-ui-check-')
server.CHATS_DB_PATH = str(Path(root.name) / 'chats.json')
server._db_cache = None
user_profile._profile_memory_instance = user_profile.UserProfileMemory(str(Path(root.name) / 'personal'))
class FixtureHandler(server.WebUIRequestHandler):
    def do_POST(self):
        if self.path == '/__fixture/shutdown':
            self._json_response({'success':True})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if self.path == '/__fixture/plan':
            with server.db_lock:
                database=server.load_chats_db()
                chat=server._active_chat(database)
                plan=('```desktop-plan\n1. Open the report\n2. Save the report\n'
                      '**Expected Output:** Saved report\n**Success Criteria:**\n'
                      '- Requested filename is visible\n- Save confirmation is visible\n'
                      'Prescribed Steps: 8\n```')
                chat['intent']='Save the report'
                chat['reviewed_plan']=plan
                chat['status']='plan_created'
                chat['chat_history']=[{'role':'user','content':'Save the report'},
                                      {'role':'assistant','content':plan,'context_refs':[
                                          {'kind':'fact','label':'Reports belong in D:/Research','source':'Your earlier statement'}]}]
                server.save_chats_db(database)
            self._json_response({'success':True})
            return
        if self.path == '/__fixture/completed':
            with server.db_lock:
                database=server.load_chats_db()
                chat=server._active_chat(database)
                chat['status']='success'
                chat['chat_history'].append({'role':'assistant','kind':'run_result','content':'Report saved.',
                    'completion_evidence':{'source':'visual','evidence':'Filename and save confirmation visible.',
                                           'criteria':[{'met':True,'evidence':'Filename visible'}]}})
                server.save_chats_db(database)
            self._json_response({'success':True})
            return
        if self.path == '/__fixture/memory':
            user_profile._profile_memory_instance.link_entities('project','Project Atlas','has_contact',
                                                                  'person','Sarah Khan',source='Project Atlas contact is Sarah Khan.')
            self._json_response({'success':True})
            return
        if self.path == '/__fixture/approval':
            request=app.interventions.open('test-run','approval','Send the reviewed report to its recipient?',{'tool_name':'click','element':'Send report'})
            app.agent_status.update(status='hitl',phase='hitl',hitl_question=request['question'],execution_chat_id=server.load_chats_db()['active_chat_id'])
            self._json_response(request)
            return
        return super().do_POST()
    def do_GET(self):
        if self.path == '/__fixture/result':
            self._json_response({'response':app.interventions.response})
            return
        return super().do_GET()
server._start_agent_task = lambda *args, **kwargs: False
httpd = ThreadingHTTPServer((os.environ.get('OMNIVLA_UI_BIND','127.0.0.1'),int(os.environ.get('OMNIVLA_UI_PORT','8000'))),FixtureHandler)
print(f'Isolated UI fixture listening on {httpd.server_address}',flush=True)
try: httpd.serve_forever()
finally: httpd.server_close(); root.cleanup()
