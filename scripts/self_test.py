"""Offline tests; do not call the game, A2A servers, or Groq."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from mcp.shared.exceptions import MCPError
from scripts.budget import reserve, complete, connection, usage
from scripts.evidence import record
from scripts.platform_score import calculate
from mas.coordinator import send_task
from mas.mcp_client import MCPGameClient, MCPGameSession
from examples.a2a_worker import Worker

def main():
    async def verify_mission_task_timeout():
        class FakeClient:
            def send_message(self, _request, context):
                assert context.timeout == 3600.0

                async def responses():
                    yield 'completed'

                return responses()

            async def close(self):
                pass

        fake_client = FakeClient()
        with patch(
            'mas.coordinator.A2ACardResolver'
        ) as resolver, patch(
            'mas.coordinator.create_client',
            new=AsyncMock(return_value=fake_client),
        ), patch(
            'mas.coordinator.ClientCallContext',
            side_effect=lambda timeout: SimpleNamespace(timeout=timeout),
        ):
            resolver.return_value.get_agent_card = AsyncMock(
                return_value=object()
            )
            result = await send_task(
                'http://127.0.0.1:9999', 'test-pilot', 'mining',
                'run_mission', {}, 'test-task',
            )
        assert result['response_count'] == 1

    asyncio.run(verify_mission_task_timeout())
    print('[PASS] Mission coordinator allows up to one hour for task completion')

    async def verify_async_mcp_call():
        client = MCPGameClient("test-pilot")
        expected = {"pilot": "test-pilot", "text": "read-only"}
        with patch.object(
            client, "call_many_async", new=AsyncMock(return_value=[expected])
        ) as call:
            result = await client.call_async(
                "spacemolt", "get_status", task_id="test-task"
            )
        assert result == expected
        call.assert_awaited_once_with(
            [("spacemolt", "get_status", None)], "test-task"
        )

    asyncio.run(verify_async_mcp_call())
    print('[PASS] MCP client supports calls inside an active event loop')

    async def verify_mcp_error_details():
        failed_session = SimpleNamespace(
            call_tool=AsyncMock(
                side_effect=MCPError(
                    code=-32603, message='Tool failed', data={'reason': 'test'}
                )
            )
        )
        game = MCPGameSession(MCPGameClient('test-pilot'), failed_session, 'test-task')
        with patch('mas.mcp_client.record') as event:
            try:
                await game.call('spacemolt', 'mine')
            except RuntimeError as exc:
                assert 'code -32603' in str(exc)
            else:
                raise AssertionError('MCP errors must be surfaced')
        assert event.call_args.kwargs['data']['data'] == {'reason': 'test'}

    asyncio.run(verify_mcp_error_details())
    print('[PASS] MCP tool errors retain server details for safe recovery')

    system_sample = (
        'System: Haven (haven) | Empire: nebula\n'
        'POIs (2):\n'
        'id\tname\ttype\tclass\tbase\tbase_type\n'
        'commerce_fields\tCommerce Fields\tasteroid_belt\tmetallic\t\t\n'
        'trade_winds\tTrade Winds\tgas_cloud\tmolecular_cloud\t\t\n'
        'Connections (2):\n'
        'system_id\tname\tdistance\n'
        'market_prime\tMarket Prime\t407 GU\n'
        "traders_rest\tTrader's Rest\t514 GU\n"
    )
    assert Worker._system_id(system_sample) == 'haven'
    assert Worker._system_id(
        'System: Haven (haven) | Empire: nebula | '
        'Security: Maximum Security (empire capital)'
    ) == 'haven'
    assert Worker._table_ids(
        system_sample, 'POIs', 'asteroid_belt'
    ) == ['commerce_fields']
    assert Worker._table_ids(
        system_sample, 'Connections'
    ) == ['market_prime', 'traders_rest']
    assert Worker._resource_remaining(
        'Iron Ore\t75\t0\t0\tyes', 'Iron Ore'
    ) == 0
    assert Worker._route_system_ids(
        '1. Haven (haven)\n2. Market Prime (market_prime)'
    ) == ['haven', 'market_prime']
    assert Worker._route_fuel('Fuel: 1/jump, 1 total (129 available)') == 1
    three_hop_map = (
        'id\tname\tempire\tvisited\tpois\tconnections\n'
        'haven\tHaven\tnebula\tyes\t2\tmarket_prime\n'
        'market_prime\tMarket Prime\tnebula\tyes\t2\thaven,gold_run\n'
        'gold_run\tGold Run\tnebula\tyes\t2\tmarket_prime,distant_iron\n'
        'distant_iron\tDistant Iron\tnebula\t\t3\tgold_run\n'
    )
    assert 'distant_iron' in Worker._nearby_system_candidates(
        three_hop_map, 'haven'
    )
    print('[PASS] Mission navigation parses live POI, resource, and fuel data')

    class FakeMiningSiteGame:
        def __init__(self):
            self.calls = []
            self.current_system = 'haven'
            self.current_poi = None

        async def call(self, tool, action, payload=None):
            self.calls.append((tool, action, payload))
            if action == 'travel':
                self.current_poi = payload['id']
                return {'text': action}
            if action == 'find_route':
                if payload['id'] == 'gold_run':
                    return {'text': (
                        'Route to gold_run (2 jumps):\n'
                        '1. Haven (haven)\n2. Market Prime (market_prime)\n'
                        '3. Gold Run (gold_run)\n'
                        'Fuel: 1/jump, 2 total (129 available)'
                    )}
                return {'text': 'Fuel: 1/jump, 0 total (129 available)'}
            if action == 'get_map':
                return {'text': (
                    'Galaxy map:\n'
                    'id\tname\tempire\tvisited\tpois\tconnections\n'
                    'haven\tHaven\tnebula\tyes\t7\tmarket_prime,traders_rest\n'
                    'market_prime\tMarket Prime\tnebula\tyes\t5\tgold_run,haven\n'
                    'traders_rest\tTrader Rest\tnebula\tyes\t5\tfactory_belt,haven\n'
                    'gold_run\tGold Run\tnebula\t\t9\tmarket_prime,bunda\n'
                    'factory_belt\tFactory Belt\tnebula\t\t4\ttraders_rest,pollux\n'
                )}
            if action == 'get_ship':
                return {'text': 'Fuel: 128/130 | Cargo: 5/110'}
            if action == 'jump':
                self.current_system = payload['id']
                return {'text': action}
            if action == 'get_system':
                if self.current_system == 'market_prime':
                    return {'text': (
                        'System: Market Prime (market_prime)\n'
                        'POIs (1):\n'
                        'id\tname\ttype\tclass\tbase\tbase_type\n'
                        'empty_belt\tEmpty Belt\tasteroid_belt\tmetallic\t\t\n'
                        'Connections (1):\n'
                        'system_id\tname\tdistance\nhaven\tHaven\t407 GU\n'
                    )}
                return {'text': (
                    'System: Gold Run (gold_run)\n'
                    'POIs (1):\n'
                    'id\tname\ttype\tclass\tbase\tbase_type\n'
                    'iron_ridge\tIron Ridge\tasteroid_belt\tmetallic\t\t\n'
                    'Connections (1):\n'
                    'system_id\tname\tdistance\nmarket_prime\tMarket Prime\t407 GU\n'
                )}
            if action == 'get_poi':
                if self.current_poi == 'commerce_fields':
                    return {'text': (
                        'POI: Commerce Fields (commerce_fields) | '
                        'Type: asteroid_belt\nResources (1):\n'
                        'Iron Ore\t75\t0\t0\tyes'
                    )}
                return {'text': (
                    'POI: Iron Ridge (iron_ridge) | Type: asteroid_belt\n'
                    'Resources (1):\nIron Ore\t75\t20\t1\tyes'
                )}
            return {'text': action}

    fake_site_game = FakeMiningSiteGame()
    fake_site_worker = Worker('mining', 'ODIN-001', ':memory:')
    with patch('examples.a2a_worker.asyncio.sleep', new=AsyncMock()), \
         patch('examples.a2a_worker.record'):
        site = asyncio.run(fake_site_worker._find_fresh_iron_site(
            fake_site_game,
            {'text': system_sample},
            {'text': 'POI: Commerce Fields (commerce_fields) | Type: asteroid_belt'},
            [], 'site-test', 'active-iron-id',
        ))
    assert site is not None
    assert Worker._poi_id(site[1]['text']) == 'iron_ridge'
    assert ('spacemolt', 'jump', {'id': 'market_prime'}) in fake_site_game.calls
    assert ('spacemolt', 'jump', {'id': 'gold_run'}) in fake_site_game.calls
    assert ('spacemolt', 'travel', {'id': 'iron_ridge'}) in fake_site_game.calls
    fake_site_worker.state.close()
    print('[PASS] Exhausted local deposit routes to a fresh nearby iron belt')

    fake_home_site_game = FakeMiningSiteGame()
    fake_home_site_worker = Worker('mining', 'ODIN-001', ':memory:')
    with patch('examples.a2a_worker.asyncio.sleep', new=AsyncMock()), \
         patch('examples.a2a_worker.record'):
        site = asyncio.run(fake_home_site_worker._find_fresh_iron_site(
            fake_home_site_game,
            {'text': system_sample},
            {'text': 'POI: Grand Exchange Station (grand_exchange_station)'},
            [], 'home-site-test', 'active-iron-id',
        ))
    assert site is not None
    assert Worker._poi_id(site[1]['text']) == 'iron_ridge'
    assert ('spacemolt', 'travel', {'id': 'commerce_fields'}) in \
        fake_home_site_game.calls
    assert ('spacemolt', 'jump', {'id': 'gold_run'}) in fake_home_site_game.calls
    fake_home_site_worker.state.close()
    print('[PASS] Home-state site search inspects and skips the depleted local belt')

    class FakeTransport:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            _ = (_exc_type, _exc, _traceback)
            return False

    class FakeSession:
        def __init__(self):
            self.initialized = 0
            self.listed_tools = 0
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            _ = (_exc_type, _exc, _traceback)
            return False

        async def initialize(self):
            self.initialized += 1

        async def list_tools(self):
            self.listed_tools += 1
            schema = {'properties': {'action': {}, 'id': {}}}
            return SimpleNamespace(tools=[
                SimpleNamespace(name='spacemolt', input_schema=schema)
            ])

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            action = arguments.get('action', 'login')
            return SimpleNamespace(
                content=[SimpleNamespace(text=f'{action} ok')],
                isError=False,
            )

    fake_session = FakeSession()
    client = MCPGameClient('test-pilot')
    with patch('mas.mcp_client.streamable_http_client',
               return_value=FakeTransport()), \
         patch('mas.mcp_client.ClientSession', return_value=fake_session), \
         patch('mas.mcp_client.keyring.get_password', return_value='placeholder'), \
         patch('mas.mcp_client.record'):
        batch = asyncio.run(client.call_many_async([
            ('spacemolt', 'get_status', None),
            ('spacemolt', 'get_active_missions', None),
        ], 'batch-test'))
    assert fake_session.initialized == 1
    assert fake_session.listed_tools == 1
    assert [arguments['action'] for _, arguments in fake_session.calls] == [
        'login', 'get_status', 'get_active_missions'
    ]
    assert len(batch) == 2
    print('[PASS] MCP batches share one authenticated session')

    with TemporaryDirectory() as temp:
        worker = Worker('mining', 'ODIN-001', str(Path(temp) / 'mas.sqlite3'))
        mock_mcp = Mock()
        mock_mcp.call_many = Mock(return_value=[
            {'text': 'Docked at Grand Exchange Station'},
            {'text': 'Iron Supply Run [iron_supply_run]'},
            {'text': 'No active missions'},
        ])
        with patch.object(worker, 'mcp', mock_mcp):
            proposal = worker._execute_role(
                {'objective': 'accept_mission', 'mission_id': 'iron_supply_run',
                 'confirm_state_change': False},
                'test-task',
            )
        assert proposal['status'] == 'confirmation_required'
        assert all(action != 'accept_mission'
                   for _, action, _ in mock_mcp.call_many.call_args.args[0])

        mock_mcp.call_many.reset_mock()
        mock_mcp.call_many.side_effect = [
            [
                {'text': 'Docked at Grand Exchange Station'},
                {'text': 'Iron Supply Run [iron_supply_run]'},
                {'text': 'No active missions'},
            ],
            [{'text': 'Mission accepted: iron_supply_run'}],
        ]
        with patch.object(worker, 'mcp', mock_mcp):
            accepted = worker._execute_role(
                {'objective': 'accept_mission', 'mission_id': 'iron_supply_run',
                 'confirm_state_change': True},
                'test-task',
            )
        assert accepted['status'] == 'mission_accepted'
        assert mock_mcp.call_many.call_args_list[-1].args[0] == [
            ('spacemolt', 'accept_mission', {'id': 'iron_supply_run'})
        ]

        class FakeGameSession:
            def __init__(self):
                self.calls = []

            async def call(self, tool, action, payload=None):
                self.calls.append((tool, action, payload))
                responses = {
                    'get_status': 'Docked at: grand_exchange_station',
                    'get_active_missions': (
                        'Iron Supply Run [active-iron-id]\n'
                        'Mine 30 units of Iron Ore: 0/30'
                    ),
                    'get_ship': 'Fuel: 130/130 | Cargo: 0/110',
                    'get_poi': 'Grand Exchange (grand_exchange)',
                    'get_system': 'System: Haven (haven)',
                }
                return {'text': responses[action]}

        class FakeSessionContext:
            def __init__(self, game):
                self.game = game

            async def __aenter__(self):
                return self.game

            async def __aexit__(self, _exc_type, _exc, _traceback):
                _ = (_exc_type, _exc, _traceback)
                return False

        fake_game = FakeGameSession()
        mock_mcp = Mock()
        mock_mcp.open_session.return_value = FakeSessionContext(fake_game)
        with patch.object(worker, 'mcp', mock_mcp):
            proposal = worker._execute_role(
                {'objective': 'run_mission', 'mission_id': 'active-iron-id',
                 'confirm_state_change': False},
                'test-task',
            )
        assert proposal['status'] == 'confirmation_required'
        assert [action for _, action, _ in fake_game.calls] == [
            'get_status', 'get_active_missions', 'get_ship', 'get_poi',
            'get_system'
        ]
        worker.state.close()
    print('[PASS] Mission acceptance requires explicit confirmation')
    print('[PASS] Mission execution requires confirmation and performs read-only preflight')

    with TemporaryDirectory() as temp:
        d = str(Path(temp)/'budget.db')
        r=reserve('mock',d);complete(r,9,6,db_path=d)
        db=connection(d); observed=usage(db);db.close()
        assert observed['requests']==1 and observed['tokens']==15
        print('[PASS] Persistent LLM budget accounting')
        log=str(Path(temp)/'events.jsonl')
        record('local.test',data={'api_key':'SECRET','msg':'gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'},path=log)
        out=Path(log).read_text()
        assert 'SECRET' not in out and 'gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345' not in out
        print('[PASS] Credential redaction')
        assert calculate({})['competition_marks_out_of_25']==0
        full={'earned':2000,'spent':1000,'ore':30,'trades':1,'exchange_sales':0,'distance':900,'systems':2}
        assert calculate(full)['competition_marks_out_of_25']==25
        assert calculate({**full,'trades':0,'exchange_sales':1})['competition_marks_out_of_25']==25
        assert calculate({**full,'ore':0})['component_marks']['Travel efficiency']==0
        print('[PASS] Platform score bands and safety gates')
    print('LOCAL SELF-TEST PASS')
if __name__=='__main__': main()
