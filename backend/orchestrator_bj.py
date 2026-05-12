"""Pipeline Orchestrator BJ – runs agents for Bytová jednotka in parallel waves.

Wave A (parallel): StrazceBJ, ForenzniAnalytik, Historik, InspektorBJ
Wave B (parallel): PorovnavacDokumentuBJ, KatastralniAnalytik, GeoValidator
Wave C (sequential, depends on all): StrategBJ

Reuses shared agents: ForenzniAnalytik, Historik, GeoValidator, KatastralniAnalytik
New BJ agents: StrazceBJ, InspektorBJ, PorovnavacDokumentuBJ, StrategBJ
"""
import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import WebSocket

from agents.base import AgentStatus, AgentResult
from agents.strazce_bj import StrazceBJAgent
from agents.forenzni_analytik import ForenzniAnalytikAgent
from agents.historik import HistorikAgent
from agents.inspektor_bj import InspektorBJAgent
from agents.geo_validator import GeoValidatorAgent
from agents.porovnavac_dokumentu_bj import PorovnavacDokumentuBJAgent
from agents.katastralni_analytik import KatastralniAnalytikAgent
from agents.strateg_bj import StrategBJAgent


# Wave definitions
BJ_WAVE_A = ["StrazceBJ", "ForenzniAnalytik", "Historik", "InspektorBJ"]
BJ_WAVE_B = ["PorovnavacDokumentuBJ", "KatastralniAnalytik", "GeoValidator"]
BJ_WAVE_C = ["StrategBJ"]


class BJPipelineOrchestrator:
    """Orchestrates the parallel-wave execution of all BJ validation agents."""

    def __init__(self, session_id: str, model_name: str = "gemini"):
        self.session_id = session_id
        self.pipeline_id = str(uuid.uuid4())[:8]
        self.model_name = model_name

        # Initialize agents (BJ-specific + shared)
        self.agents = {
            "StrazceBJ": StrazceBJAgent(model_name=model_name),
            "ForenzniAnalytik": ForenzniAnalytikAgent(model_name=model_name),
            "Historik": HistorikAgent(model_name=model_name),
            "InspektorBJ": InspektorBJAgent(model_name=model_name),
            "GeoValidator": GeoValidatorAgent(model_name=model_name),
            "PorovnavacDokumentuBJ": PorovnavacDokumentuBJAgent(model_name=model_name),
            "KatastralniAnalytik": KatastralniAnalytikAgent(model_name=model_name),
            "StrategBJ": StrategBJAgent(model_name=model_name),
        }
        self.agent_order = BJ_WAVE_A + BJ_WAVE_B + BJ_WAVE_C
        self.active_connections: list[WebSocket] = []
        self.is_running = False
        self.results = {}
        # Limit concurrency to 2 agents at a time to prevent Render OOM (512MB RAM)
        self.semaphore = asyncio.Semaphore(2)

    async def broadcast(self, message: dict):
        """Broadcast a message to all WebSocket connections."""
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def _notify_status(self, agent_name: str, status: str, extra: dict = None):
        """Send agent status update via WebSocket."""
        msg = {
            "type": "agent_status",
            "pipeline_id": self.pipeline_id,
            "agent": agent_name,
            "status": status,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        await self.broadcast(msg)

    async def _notify_log(self, agent_name: str, message: str, level: str = "info"):
        """Send agent log via WebSocket."""
        await self.broadcast({
            "type": "agent_log",
            "pipeline_id": self.pipeline_id,
            "agent": agent_name,
            "message": message,
            "level": level,
            "timestamp": time.time(),
        })

    async def _notify_wave(self, wave_name: str, agents: list[str]):
        """Notify frontend that a new wave is starting."""
        await self.broadcast({
            "type": "pipeline_wave",
            "pipeline_id": self.pipeline_id,
            "wave": wave_name,
            "agents": agents,
            "timestamp": time.time(),
        })

    async def _run_agent(self, agent_name: str, context: dict, agent_results: dict) -> AgentResult:
        """Run a single agent and broadcast its status."""
        import gc
        agent = self.agents[agent_name]

        if context.get("custom_prompts", {}).get(agent_name):
            agent.system_prompt = context["custom_prompts"][agent_name]

        await self._notify_status(agent_name, "processing")
        await self._notify_log(agent_name, f"Agent {agent_name} čeká ve frontě (omezení paměti)...")

        run_context = {**context, "agent_results": dict(agent_results)}
        
        async with self.semaphore:
            await self._notify_log(agent_name, f"Agent {agent_name} se spouští...")
            result = await agent.execute(run_context)

        for log_entry in agent.logs:
            await self._notify_log(agent_name, log_entry.message, log_entry.level)

        await self._notify_status(
            agent_name,
            result.status.value,
            {"elapsed_time": agent.get_elapsed_time()},
        )

        self.results[agent_name] = agent.to_dict()
        gc.collect()
        return result

    async def _run_wave(self, wave_name: str, agent_names: list[str], context: dict, agent_results: dict) -> dict:
        """Run a list of agents in parallel."""
        await self._notify_wave(wave_name, agent_names)

        tasks = {
            name: asyncio.create_task(self._run_agent(name, context, agent_results))
            for name in agent_names
        }

        wave_results = {}
        for name, task in tasks.items():
            try:
                wave_results[name] = await task
            except Exception as e:
                await self._notify_log(name, f"Agent selhal: {e}", "error")
                await self._notify_status(name, "fail")
                self.results[name] = {
                    "name": name, "status": "fail",
                    "summary": f"Chyba: {e}", "errors": [str(e)],
                }
                wave_results[name] = AgentResult(
                    status=AgentStatus.FAIL,
                    summary=f"Chyba: {e}",
                    errors=[str(e)],
                )

        return wave_results

    async def run_pipeline(self, context: dict) -> dict:
        """Execute the full BJ pipeline in parallel waves."""
        self.is_running = True
        start_time = time.time()
        import gc

        await self.broadcast({
            "type": "pipeline_start",
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "timestamp": start_time,
            "agents": self.agent_order,
            "pipeline_type": "bj",
            "waves": {
                "A": BJ_WAVE_A,
                "B": BJ_WAVE_B,
                "C": BJ_WAVE_C,
            },
        })

        agent_results = {}

        # ── Wave A: Independent agents ──
        print("[BJ Pipeline] === Wave A: StrazceBJ, ForenzniAnalytik, Historik, InspektorBJ ===")
        wave_a = await self._run_wave("A", BJ_WAVE_A, context, agent_results)
        agent_results.update(wave_a)
        gc.collect()

        # ── Wave B: Depends on Wave A ──
        print("[BJ Pipeline] === Wave B: PorovnavacDokumentuBJ, KatastralniAnalytik, GeoValidator ===")
        wave_b = await self._run_wave("B", BJ_WAVE_B, context, agent_results)
        agent_results.update(wave_b)
        gc.collect()

        # ── Wave C: StrategBJ – aggregates everything ──
        print("[BJ Pipeline] === Wave C: StrategBJ ===")
        await self._notify_wave("C", BJ_WAVE_C)
        strategist = self.agents["StrategBJ"]
        strategist_context = {**context, "agent_results": agent_results}

        if context.get("custom_prompts", {}).get("StrategBJ"):
            strategist.system_prompt = context["custom_prompts"]["StrategBJ"]

        await self._notify_status("StrategBJ", "processing")
        await self._notify_log("StrategBJ", "StrategBJ agreguje výsledky všech agentů...")

        try:
            strategist_result = await strategist.execute(strategist_context)
        except Exception as e:
            await self._notify_log("StrategBJ", f"Chyba StrategBJ: {e}", "error")
            strategist_result = AgentResult(
                status=AgentStatus.FAIL,
                summary=f"StrategBJ selhal: {e}",
                errors=[str(e)],
                details={"semaphore": "UNKNOWN", "semaphore_color": "gray"},
            )

        agent_results["StrategBJ"] = strategist_result

        for log_entry in strategist.logs:
            await self._notify_log("StrategBJ", log_entry.message, log_entry.level)

        await self._notify_status(
            "StrategBJ",
            strategist_result.status.value,
            {"elapsed_time": strategist.get_elapsed_time()},
        )

        self.results["StrategBJ"] = strategist.to_dict()
        gc.collect()

        total_time = round(time.time() - start_time, 2)
        self.is_running = False
        print(f"[BJ Pipeline] COMPLETE in {total_time}s")

        final_result = {
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "pipeline_type": "bj",
            "total_time": total_time,
            "semaphore": strategist_result.details.get("semaphore", "UNKNOWN"),
            "semaphore_color": strategist_result.details.get("semaphore_color", "gray"),
            "final_category": strategist_result.category,
            "agents": self.results,
            "property_data": context.get("property_data"),
            "property_address": context.get("property_address"),
        }

        await self.broadcast({
            "type": "pipeline_complete",
            "pipeline_id": self.pipeline_id,
            "result": final_result,
            "timestamp": time.time(),
        })

        return final_result

    def get_state(self) -> dict:
        """Get current pipeline state for API response."""
        return {
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "pipeline_type": "bj",
            "is_running": self.is_running,
            "agents": {
                name: agent.to_dict()
                for name, agent in self.agents.items()
            },
        }
