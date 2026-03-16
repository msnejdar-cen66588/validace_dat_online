import asyncio
from backend.agents.odhadce import OdhadceAgent

async def test():
    agent = OdhadceAgent()
    res = await agent.run({"property_address": "Testovaci 123", "property_data": {"celkova_podlahova_plocha": 150, "stav_rodinneho_domu": "Dobrý"}})
    print(res)

if __name__ == "__main__":
    asyncio.run(test())
