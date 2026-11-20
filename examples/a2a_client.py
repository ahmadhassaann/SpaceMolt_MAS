"""A2A task submission client for the MAS workers."""
import argparse,asyncio,httpx,json
from a2a.client import A2ACardResolver,ClientConfig,create_client
from a2a.helpers import new_text_message
from a2a.types import Role,SendMessageRequest

async def main(url):
    async with httpx.AsyncClient(timeout=20.0) as http:
        card=await A2ACardResolver(httpx_client=http,base_url=url).get_agent_card()
        print('Discovered A2A agent:',card.name)
    client=await create_client(agent=card,client_config=ClientConfig(streaming=False))
    message=new_text_message(json.dumps({'pilot':args_pilot,'objective':args_objective,
                                         'dry_run':args_dry_run,
                                         'confirm_state_change':args_confirm}),role=Role.ROLE_USER)
    async for response in client.send_message(SendMessageRequest(message=message)):
        print('A2A response:',str(response)[:2000])
    await client.close()
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--url',default='http://127.0.0.1:9999')
    p.add_argument('--pilot',default=None)
    p.add_argument('--objective',default='observe')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--confirm',action='store_true')
    args=p.parse_args()
    args_pilot=args.pilot
    args_objective=args.objective
    args_dry_run=args.dry_run
    args_confirm=args.confirm
    asyncio.run(main(args.url))
