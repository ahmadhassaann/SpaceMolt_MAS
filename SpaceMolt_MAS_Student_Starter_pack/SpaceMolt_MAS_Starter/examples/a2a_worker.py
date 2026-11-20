"""Independent local A2A worker connected to authenticated SpaceMolt MCP.
Start: python examples/a2a_worker.py --role mining --port 9999
"""
import argparse,asyncio,json
import uvicorn
from starlette.applications import Starlette
from a2a.server.agent_execution import AgentExecutor,RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes,create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore,TaskUpdater
from a2a.types import AgentCapabilities,AgentCard,AgentInterface,AgentSkill,TaskState
from a2a.helpers import get_message_text, new_task_from_user_message
from a2a.helpers import new_text_message,new_text_part
from mas.mcp_client import MCPGameClient
from mas.state import MASState
from scripts.evidence import record

class Worker(AgentExecutor):
    def __init__(self,role,pilot=None,db_path='logs/mas.sqlite3'):
        self.role=role
        self.pilot=pilot
        self.state=MASState(db_path)
        self.mcp=MCPGameClient(pilot,db_path) if pilot else None
    async def execute(self,context:RequestContext,event_queue:EventQueue)->None:
        task=context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None: await event_queue.enqueue_event(task)
        updater=TaskUpdater(event_queue=event_queue,task_id=task.id,context_id=task.context_id)
        await updater.update_status(state=TaskState.TASK_STATE_WORKING,message=new_text_message('Working on request'))
        request=get_message_text(context.message) or ''
        try:
            payload=json.loads(request)
        except json.JSONDecodeError:
            payload={'objective':request}
        pilot=payload.get('pilot') or self.pilot
        if not pilot or self.mcp is None:
            raise RuntimeError('Worker requires --pilot and that pilot password in Windows Credential Manager')
        if pilot != self.pilot:
            raise RuntimeError(f'Worker is bound to {self.pilot}; refusing task for {pilot}')
        objective=payload.get('objective','observe')
        record('a2a.task.received',agent=f'a2a-{self.role}',task_id=task.id,
               data={'role':self.role,'pilot':pilot,'objective':objective})
        if payload.get('dry_run'):
            result={'role':self.role,'status':'dry_run','task_request':payload,
                    'next_step':'authenticate and execute through MCP'}
        else:
            result=await asyncio.to_thread(self._execute_role,payload,task.id)
        await updater.add_artifact(parts=[new_text_part(text=json.dumps(result,ensure_ascii=False,default=str),
                                                        media_type='text/plain')])
        await updater.update_status(state=TaskState.TASK_STATE_COMPLETED,
                                    message=new_text_message(json.dumps(result,ensure_ascii=False)[:1000]))

    def _execute_role(self,payload,task_id):
        if not self.mcp:
            raise RuntimeError('MCP worker is not configured')
        if self.role=='mining':
            status=self.mcp.call('spacemolt','get_status',task_id=task_id)
            missions=self.mcp.call('spacemolt','get_missions',task_id=task_id)
            system=self.mcp.call('spacemolt','get_system',task_id=task_id)
            outcomes=[status,missions,system]
            objective=payload.get('objective','mine')
            if objective=='mine' and payload.get('confirm_state_change'):
                location=payload.get('poi')
                if location:
                    travel=self.mcp.call('spacemolt','travel',{'target':location},task_id)
                    outcomes.append(travel)
                mine=self.mcp.call('spacemolt','mine',task_id=task_id)
                outcomes.append(mine)
            return {'role':'mining','status':'completed','pilot':self.pilot,
                    'objective':objective,'observed':outcomes}
        if self.role=='trading':
            status=self.mcp.call('spacemolt','get_status',task_id=task_id)
            missions=self.mcp.call('spacemolt','get_missions',task_id=task_id)
            market=self.mcp.call('spacemolt_market','view_market',task_id=task_id)
            outcomes=[status,missions,market]
            objective=payload.get('objective','assess')
            if objective=='buy' and payload.get('confirm_state_change'):
                allowed={'item','quantity','price'}
                buy_payload={k:v for k,v in payload.items() if k in allowed}
                outcomes.append(self.mcp.call('spacemolt_market','buy',buy_payload,task_id))
            elif objective=='sell' and payload.get('confirm_state_change'):
                allowed={'item','quantity','price'}
                sell_payload={k:v for k,v in payload.items() if k in allowed}
                outcomes.append(self.mcp.call('spacemolt_market','sell',sell_payload,task_id))
            return {'role':'trading','status':'completed','pilot':self.pilot,
                    'objective':objective,'observed':outcomes}
        raise RuntimeError(f'Unknown role: {self.role}')
    async def cancel(self,context:RequestContext,event_queue:EventQueue)->None:
        # This demonstration has no long-running operation to cancel.
        return

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--role',choices=('mining','trading'),default='mining')
    parser.add_argument('--pilot',required=True)
    parser.add_argument('--port',type=int,default=9999)
    args=parser.parse_args()
    card=AgentCard(name=f'FAST {args.role.title()} Worker',description=f'Authenticated SpaceMolt {args.role} A2A worker',version='1.0.0',
                   default_input_modes=['text/plain'],default_output_modes=['text/plain'],
                   capabilities=AgentCapabilities(streaming=False),
                   supported_interfaces=[AgentInterface(protocol_binding='JSONRPC',url=f'http://127.0.0.1:{args.port}',protocol_version='1.0')],
                   skills=[AgentSkill(id=f'{args.role}_task',name=f'{args.role.title()} Task',description='Acknowledges an assigned task',input_modes=['text/plain'],output_modes=['text/plain'],tags=['mas','training'],examples=['inspect current task'])])
    handler=DefaultRequestHandler(agent_executor=Worker(args.role,args.pilot),task_store=InMemoryTaskStore(),agent_card=card)
    routes=[*create_agent_card_routes(card),*create_jsonrpc_routes(handler,'/')]
    print(f'A2A {args.role} at http://127.0.0.1:{args.port}/.well-known/agent-card.json')
    uvicorn.run(Starlette(routes=routes),host='127.0.0.1',port=args.port)
if __name__=='__main__':main()
