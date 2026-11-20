"""Independent local A2A worker connected to authenticated SpaceMolt MCP.
Start: python examples/a2a_worker.py --role mining --port 9999
"""
import argparse,asyncio,json,sys
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
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
            objective=payload.get('objective','mine')
            if objective=='run_mission':
                try:
                    return asyncio.run(self._run_iron_supply_mission(payload,task_id))
                except ExceptionGroup as exc:
                    raise RuntimeError(self._exception_summary(exc)) from exc
            if objective=='accept_mission':
                mission_id=payload.get('mission_id')
                if not mission_id:
                    raise ValueError('accept_mission requires a mission_id')
                status,missions,active=self.mcp.call_many([
                    ('spacemolt','get_status',None),
                    ('spacemolt','get_missions',None),
                    ('spacemolt','get_active_missions',None),
                ],task_id)
                active_text=active.get('text','')
                outcomes=[status,missions,active]
                if mission_id in active_text:
                    return {'role':'mining','status':'already_active','pilot':self.pilot,
                            'mission_id':mission_id,'observed':outcomes}
                if mission_id not in missions.get('text',''):
                    raise RuntimeError(f'Mission is not available at this station: {mission_id}')
                if not payload.get('confirm_state_change'):
                    return {'role':'mining','status':'confirmation_required',
                            'pilot':self.pilot,'mission_id':mission_id,
                            'observed':outcomes}
                accepted=self.mcp.call_many([
                    ('spacemolt','accept_mission',{'id':mission_id}),
                ],task_id)[0]
                record('mining.mission_accepted',agent='a2a-mining',task_id=task_id,
                       data={'pilot':self.pilot,'mission_id':mission_id})
                return {'role':'mining','status':'mission_accepted','pilot':self.pilot,
                        'mission_id':mission_id,'observed':outcomes+[accepted]}
            status=self.mcp.call('spacemolt','get_status',task_id=task_id)
            missions=self.mcp.call('spacemolt','get_missions',task_id=task_id)
            outcomes=[status,missions]
            system=self.mcp.call('spacemolt','get_system',task_id=task_id)
            outcomes.append(system)
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

    @staticmethod
    def _iron_mission_progress(text):
        match=re.search(r'Mine 30 units of Iron Ore:\s*(\d+)/30',text,re.IGNORECASE)
        if not match:
            raise RuntimeError('Active mission did not report Iron Ore progress')
        return int(match.group(1))

    @staticmethod
    def _ship_metric(text,label):
        match=re.search(rf'{re.escape(label)}:\s*(\d+)/(\d+)',text)
        if not match:
            raise RuntimeError(f'Ship status did not report {label}')
        return int(match.group(1)),int(match.group(2))

    @staticmethod
    def _resource_remaining(text,resource):
        match=re.search(
            rf'(?im)^\s*{re.escape(resource)}\s+\d+\s+(\d+)\s+\d+\s+\w+',
            text,
        )
        return int(match.group(1)) if match else None

    @staticmethod
    def _poi_id(text):
        match=re.search(r'(?m)^POI:.*\(([^)]+)\)',text)
        if not match:
            raise RuntimeError('Current POI ID was not reported')
        return match.group(1)

    @staticmethod
    def _system_id(text):
        match=re.search(r'(?m)^System:\s+[^(\r\n]*\(([a-z0-9_]+)\)',text)
        if not match:
            raise RuntimeError('Current system ID was not reported')
        return match.group(1)

    @staticmethod
    def _table_ids(text,section,field_value=None):
        match=re.search(
            rf'(?ms)^{section} \(\d+\):\n(.*?)(?=^[A-Za-z][A-Za-z ]* \(|\Z)',
            text,
        )
        if not match:
            return []
        rows=match.group(1).splitlines()[1:]
        ids=[]
        for row in rows:
            columns=[column.strip() for column in row.split('\t')]
            if not columns or not re.fullmatch(r'[a-z0-9_]+',columns[0]):
                continue
            if field_value is None or (
                len(columns)>2 and columns[2]==field_value
            ):
                ids.append(columns[0])
        return ids

    @staticmethod
    def _route_system_ids(text):
        return re.findall(r'(?m)^\s*\d+\.\s+.*\(([^)]+)\)',text)

    @staticmethod
    def _route_fuel(text):
        match=re.search(r'Fuel:.*?(\d+)\s+total',text)
        if not match:
            raise RuntimeError('Route did not report its fuel requirement')
        return int(match.group(1))

    @staticmethod
    def _map_graph(text):
        graph={}
        for line in text.splitlines():
            columns=[column.strip() for column in line.split('\t')]
            if len(columns)<6 or not re.fullmatch(r'[a-z0-9_]+',columns[0]):
                continue
            graph[columns[0]]=(
                columns[2],columns[3].lower()=='yes',
                [item for item in columns[5].split(',') if item],
            )
        return graph

    @staticmethod
    def _nearby_system_candidates(text,start,limit=4):
        graph=Worker._map_graph(text)
        if start not in graph:
            return []
        distances={start:0}
        pending=[start]
        while pending:
            current=pending.pop(0)
            distance=distances[current]
            if distance>=3:
                continue
            for neighbor in graph[current][2]:
                if neighbor in graph and neighbor not in distances:
                    distances[neighbor]=distance+1
                    pending.append(neighbor)
        empire=graph[start][0]
        candidates=[
            system_id for system_id,distance in distances.items()
            if system_id!=start and distance<=3 and
            not graph[system_id][1] and
            (not graph[system_id][0] or graph[system_id][0]==empire)
        ]
        mining_terms=('gold','iron','ore','mine','quarry')
        candidates.sort(key=lambda system_id:(
            0 if any(term in system_id for term in mining_terms) else
            1 if 'factory' in system_id or 'belt' in system_id else 2,
            distances[system_id],
            system_id,
        ))
        return candidates[:limit]

    @staticmethod
    def _exception_summary(exc):
        if isinstance(exc,BaseExceptionGroup):
            return '; '.join(
                Worker._exception_summary(item) for item in exc.exceptions
            )
        return f'{type(exc).__name__}: {exc}'

    async def _find_fresh_iron_site(self,game,system,poi,observed,task_id,mission_id):
        current_system=self._system_id(system.get('text',''))
        current_poi=self._poi_id(poi.get('text',''))
        for belt_id in self._table_ids(
            system.get('text',''),'POIs','asteroid_belt'
        ):
            if belt_id==current_poi:
                continue
            step=await game.call('spacemolt','travel',{'id':belt_id})
            observed.append(step)
            record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,
                         'step':'inspect_local_mining_belt','poi':belt_id})
            await asyncio.sleep(10)
            poi=await game.call('spacemolt','get_poi')
            observed.append(poi)
            if (self._resource_remaining(poi.get('text',''),'Iron Ore') or 0)>0:
                ship=await game.call('spacemolt','get_ship')
                observed.append(ship)
                return system,poi,ship

        galaxy=await game.call('spacemolt','get_map')
        observed.append(galaxy)
        candidates=self._nearby_system_candidates(
            galaxy.get('text',''),current_system
        )
        record('mining.iron_site_search',agent='a2a-mining',task_id=task_id,
               data={'pilot':self.pilot,'mission_id':mission_id,
                     'current_system':current_system,'candidates':candidates})
        for target_system in candidates:
            route=await game.call('spacemolt','find_route',{'id':target_system})
            observed.append(route)
            route_ids=self._route_system_ids(route.get('text',''))
            record('mining.iron_site_route',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,
                         'target_system':target_system,'route':route_ids})
            if not route_ids:
                continue
            home_route=await game.call(
                'spacemolt','find_route',{'id':'grand_exchange_station'}
            )
            observed.append(home_route)
            ship=await game.call('spacemolt','get_ship')
            observed.append(ship)
            fuel,_=self._ship_metric(ship.get('text',''),'Fuel')
            required=self._route_fuel(route.get('text','')) + \
                self._route_fuel(home_route.get('text','')) + 10
            if fuel<required:
                raise RuntimeError(
                    'Not enough fuel to inspect another system and preserve a return reserve'
                )
            for next_system in route_ids[1:]:
                step=await game.call('spacemolt','jump',{'id':next_system})
                observed.append(step)
                record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                       data={'pilot':self.pilot,'mission_id':mission_id,
                             'step':'jump_to_mining_system','system':next_system})
                await asyncio.sleep(10)
                system=await game.call('spacemolt','get_system')
                observed.append(system)
                current_system=self._system_id(system.get('text',''))
                if current_system!=next_system:
                    raise RuntimeError(
                        f'Jump did not arrive in the planned system: {next_system}'
                    )
            for belt_id in self._table_ids(
                system.get('text',''),'POIs','asteroid_belt'
            ):
                step=await game.call('spacemolt','travel',{'id':belt_id})
                observed.append(step)
                record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                       data={'pilot':self.pilot,'mission_id':mission_id,
                             'step':'inspect_mining_belt','poi':belt_id})
                await asyncio.sleep(10)
                poi=await game.call('spacemolt','get_poi')
                observed.append(poi)
                if (self._resource_remaining(poi.get('text',''),'Iron Ore') or 0)>0:
                    ship=await game.call('spacemolt','get_ship')
                    observed.append(ship)
                    return system,poi,ship
        return None

    async def _return_to_grand_exchange(self,game,observed,task_id,mission_id):
        route=await game.call(
            'spacemolt','find_route',{'id':'grand_exchange_station'}
        )
        observed.append(route)
        ship=await game.call('spacemolt','get_ship')
        observed.append(ship)
        fuel,_=self._ship_metric(ship.get('text',''),'Fuel')
        if fuel<self._route_fuel(route.get('text',''))+10:
            raise RuntimeError('Not enough fuel to return to Grand Exchange safely')
        route_ids=self._route_system_ids(route.get('text',''))
        system=await game.call('spacemolt','get_system')
        observed.append(system)
        current_system=self._system_id(system.get('text',''))
        for next_system in route_ids:
            if next_system==current_system:
                continue
            step=await game.call('spacemolt','jump',{'id':next_system})
            observed.append(step)
            record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,
                         'step':'jump_home','system':next_system})
            await asyncio.sleep(10)
            system=await game.call('spacemolt','get_system')
            observed.append(system)
            current_system=self._system_id(system.get('text',''))
        poi=await game.call('spacemolt','get_poi')
        observed.append(poi)
        if 'Grand Exchange (grand_exchange)' not in poi.get('text',''):
            step=await game.call(
                'spacemolt','travel',{'id':'grand_exchange_station'}
            )
            observed.append(step)
            record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,
                         'step':'travel_home'})
            await asyncio.sleep(10)
        status=await game.call('spacemolt','get_status')
        observed.append(status)
        if 'Docked at: grand_exchange_station' not in status.get('text',''):
            step=await game.call('spacemolt','dock')
            observed.append(step)
            record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,'step':'dock'})
            await asyncio.sleep(10)
            status=await game.call('spacemolt','get_status')
            observed.append(status)
        if 'Docked at: grand_exchange_station' not in status.get('text',''):
            raise RuntimeError('Ship did not dock at Grand Exchange')
        return status

    async def _run_iron_supply_mission(self,payload,task_id):
        if self.mcp is None:
            raise RuntimeError('MCP worker is not configured')
        mission_id=payload.get('mission_id')
        if not mission_id:
            raise ValueError('run_mission requires the active mission ID')
        observed=[]
        async with self.mcp.open_session(task_id) as game:
            status=await game.call('spacemolt','get_status')
            active=await game.call('spacemolt','get_active_missions')
            ship=await game.call('spacemolt','get_ship')
            poi=await game.call('spacemolt','get_poi')
            system=await game.call('spacemolt','get_system')
            observed.extend([status,active,ship,poi,system])
            active_text=active.get('text','')
            if mission_id not in active_text:
                completed=await game.call('spacemolt','completed_missions')
                observed.append(completed)
                if mission_id in completed.get('text',''):
                    return {'role':'mining','status':'already_completed',
                            'pilot':self.pilot,'mission_id':mission_id,
                            'observed':observed}
                raise RuntimeError(f'Active Iron Supply Run not found: {mission_id}')
            progress=self._iron_mission_progress(active_text)
            if not payload.get('confirm_state_change'):
                return {'role':'mining','status':'confirmation_required',
                        'pilot':self.pilot,'mission_id':mission_id,
                        'progress':progress,'observed':observed}

            status_text=status.get('text','')
            poi_text=poi.get('text','')
            at_home='Docked at: grand_exchange_station' in status_text
            at_asteroid='Type: asteroid_belt' in poi_text
            if not at_home and not at_asteroid:
                raise RuntimeError(
                    'Mission runner requires Grand Exchange or an asteroid belt'
                )
            if progress<30 and at_home:
                step=await game.call('spacemolt','undock')
                observed.append(step)
                record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                       data={'pilot':self.pilot,'mission_id':mission_id,'step':'undock'})
                await asyncio.sleep(10)
                site=await self._find_fresh_iron_site(
                    game,system,poi,observed,task_id,mission_id
                )
                if site is None:
                    await self._return_to_grand_exchange(
                        game,observed,task_id,mission_id
                    )
                    raise RuntimeError(
                        'No fresh Iron Ore belt was found in the nearby charted systems'
                    )
                system,poi,ship=site
                poi_text=poi.get('text','')

            if progress<30:
                cargo_used,cargo_capacity=self._ship_metric(
                    ship.get('text',''),'Cargo'
                )
                if cargo_capacity-cargo_used<30-progress:
                    await self._return_to_grand_exchange(
                        game,observed,task_id,mission_id
                    )
                    raise RuntimeError('Insufficient free cargo capacity for mission ore')
                remaining=self._resource_remaining(poi_text,'Iron Ore')
                if remaining is None or remaining==0:
                    site=await self._find_fresh_iron_site(
                        game,system,poi,observed,task_id,mission_id
                    )
                    if site is None:
                        await self._return_to_grand_exchange(
                            game,observed,task_id,mission_id
                        )
                        raise RuntimeError(
                            'No fresh Iron Ore belt was found in the nearby charted systems'
                        )
                    system,poi,ship=site
                stalls=0
                for _ in range(30-progress+10):
                    try:
                        mined=await game.call('spacemolt','mine')
                        observed.append(mined)
                    except RuntimeError:
                        poi=await game.call('spacemolt','get_poi')
                        observed.append(poi)
                        if (self._resource_remaining(
                                poi.get('text',''),'Iron Ore') or 0)>0:
                            await self._return_to_grand_exchange(
                                game,observed,task_id,mission_id
                            )
                            raise
                        site=await self._find_fresh_iron_site(
                            game,system,poi,observed,task_id,mission_id
                        )
                        if site is None:
                            await self._return_to_grand_exchange(
                                game,observed,task_id,mission_id
                            )
                            raise RuntimeError(
                                'Iron Ore deposit depleted; no fresh adjacent belt found'
                            )
                        system,poi,ship=site
                        continue
                    record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                           data={'pilot':self.pilot,'mission_id':mission_id,'step':'mine'})
                    active=await game.call('spacemolt','get_active_missions')
                    ship=await game.call('spacemolt','get_ship')
                    poi=await game.call('spacemolt','get_poi')
                    observed.extend([active,ship,poi])
                    updated=self._iron_mission_progress(active.get('text',''))
                    cargo_used,cargo_capacity=self._ship_metric(
                        ship.get('text',''),'Cargo'
                    )
                    if updated<=progress:
                        stalls+=1
                    else:
                        stalls=0
                    progress=updated
                    if progress>=30:
                        break
                    if cargo_used>=cargo_capacity:
                        await self._return_to_grand_exchange(
                            game,observed,task_id,mission_id
                        )
                        raise RuntimeError('Cargo is full before mission completion')
                    remaining=self._resource_remaining(poi.get('text',''),'Iron Ore')
                    if remaining is None or remaining==0:
                        site=await self._find_fresh_iron_site(
                            game,system,poi,observed,task_id,mission_id
                        )
                        if site is None:
                            await self._return_to_grand_exchange(
                                game,observed,task_id,mission_id
                            )
                            raise RuntimeError(
                                'Iron Ore deposit depleted; no fresh adjacent belt found'
                            )
                        system,poi,ship=site
                        stalls=0
                        continue
                    if stalls>=2:
                        site=await self._find_fresh_iron_site(
                            game,system,poi,observed,task_id,mission_id
                        )
                        if site is None:
                            await self._return_to_grand_exchange(
                                game,observed,task_id,mission_id
                            )
                            raise RuntimeError(
                                'Mining made no progress twice and no fresh Iron Ore belt was found'
                            )
                        system,poi,ship=site
                        stalls=0
                    await asyncio.sleep(10)
                if progress<30:
                    await self._return_to_grand_exchange(
                        game,observed,task_id,mission_id
                    )
                    raise RuntimeError('Mining attempt limit reached before mission completion')

            status=await self._return_to_grand_exchange(
                game,observed,task_id,mission_id
            )
            active=await game.call('spacemolt','get_active_missions')
            if mission_id not in active.get('text','') or \
                    self._iron_mission_progress(active.get('text',''))<30:
                raise RuntimeError('Mission is not ready to turn in')
            completed=await game.call('spacemolt','complete_mission',
                                      {'id':mission_id})
            observed.extend([status,active,completed])
            record('mining.mission_step',agent='a2a-mining',task_id=task_id,
                   data={'pilot':self.pilot,'mission_id':mission_id,'step':'complete'})
            verified=await game.call('spacemolt','completed_missions')
            still_active=await game.call('spacemolt','get_active_missions')
            observed.extend([verified,still_active])
            if mission_id in still_active.get('text','') or \
                    'Iron Supply Run' not in verified.get('text',''):
                raise RuntimeError('Mission completion was not confirmed')
            return {'role':'mining','status':'mission_completed','pilot':self.pilot,
                    'mission_id':mission_id,'progress':progress,'observed':observed}

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
