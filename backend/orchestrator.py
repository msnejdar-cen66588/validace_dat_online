"""Pipeline Orchestrator – runs agents in parallel waves with real-time WebSocket updates.

Wave A (parallel): Strazce, ForenzniAnalytik, Historik, Inspektor
Wave B (parallel): PorovnavacDokumentu, KatastralniAnalytik, GeoValidator
Wave C (sequential, depends on all): Strateg

No preventive sleeps – exponential backoff on 429 is handled inside LLMClient.
"""
import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import WebSocket

from agents.base import AgentStatus, AgentResult
from agents.strazce import StrazceAgent
from agents.forenzni_analytik import ForenzniAnalytikAgent
from agents.historik import HistorikAgent
from agents.inspektor import InspektorAgent
from agents.geo_validator import GeoValidatorAgent
from agents.porovnavac_dokumentu import PorovnavacDokumentuAgent
from agents.katastralni_analytik import KatastralniAnalytikAgent
from agents.strateg import StrategAgent


# Wave definitions – order matters for frontend display
WAVE_A = ["Strazce", "ForenzniAnalytik", "Historik", "Inspektor"]
WAVE_B = ["PorovnavacDokumentu", "KatastralniAnalytik", "GeoValidator"]
WAVE_C = ["Strateg"]


class PipelineOrchestrator:
    """Orchestrates the parallel-wave execution of all validation agents."""

    def __init__(self, session_id: str, model_name: str = "gemini"):
        self.session_id = session_id
        self.pipeline_id = str(uuid.uuid4())[:8]
        self.model_name = model_name

        # Initialize agents
        self.agents = {
            "Strazce": StrazceAgent(model_name=model_name),
            "ForenzniAnalytik": ForenzniAnalytikAgent(model_name=model_name),
            "Historik": HistorikAgent(model_name=model_name),
            "Inspektor": InspektorAgent(model_name=model_name),
            "GeoValidator": GeoValidatorAgent(model_name=model_name),
            "PorovnavacDokumentu": PorovnavacDokumentuAgent(model_name=model_name),
            "KatastralniAnalytik": KatastralniAnalytikAgent(model_name=model_name),
            "Strateg": StrategAgent(model_name=model_name),
        }
        self.agent_order = WAVE_A + WAVE_B + WAVE_C
        self.active_connections: list[WebSocket] = []
        self.is_running = False
        self.results = {}

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
        """Notify frontend that a new wave is starting (multiple agents launching)."""
        await self.broadcast({
            "type": "pipeline_wave",
            "pipeline_id": self.pipeline_id,
            "wave": wave_name,
            "agents": agents,
            "timestamp": time.time(),
        })

    async def _run_agent(self, agent_name: str, context: dict, agent_results: dict) -> AgentResult:
        """Run a single agent and broadcast its status. Safe to run concurrently."""
        import gc
        agent = self.agents[agent_name]

        if context.get("custom_prompts", {}).get(agent_name):
            agent.system_prompt = context["custom_prompts"][agent_name]

        await self._notify_status(agent_name, "processing")
        await self._notify_log(agent_name, f"Agent {agent_name} starting...")

        run_context = {**context, "agent_results": dict(agent_results)}
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
        """Run a list of agents in parallel. Returns dict of {agent_name: AgentResult}."""
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
        """Execute the full pipeline in parallel waves."""
        self.is_running = True
        start_time = time.time()
        import gc

        await self.broadcast({
            "type": "pipeline_start",
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "timestamp": start_time,
            "agents": self.agent_order,
            # Let frontend know the wave structure so it can animate correctly
            "waves": {
                "A": WAVE_A,
                "B": WAVE_B,
                "C": WAVE_C,
            },
        })

        agent_results = {}

        # ── Wave A: Independent agents (no dependencies) ──────────────────────
        print("[Pipeline] === Wave A: Strazce, ForenzniAnalytik, Historik, Inspektor ===")
        wave_a = await self._run_wave("A", WAVE_A, context, agent_results)
        agent_results.update(wave_a)
        gc.collect()

        # ── Wave B: Depends on Wave A results ─────────────────────────────────
        print("[Pipeline] === Wave B: PorovnavacDokumentu, KatastralniAnalytik, GeoValidator ===")
        wave_b = await self._run_wave("B", WAVE_B, context, agent_results)
        agent_results.update(wave_b)
        gc.collect()

        # ── Wave C: Strateg – aggregates everything ───────────────────────────
        print("[Pipeline] === Wave C: Strateg ===")
        await self._notify_wave("C", WAVE_C)
        strategist = self.agents["Strateg"]
        strategist_context = {**context, "agent_results": agent_results}

        if context.get("custom_prompts", {}).get("Strateg"):
            strategist.system_prompt = context["custom_prompts"]["Strateg"]

        await self._notify_status("Strateg", "processing")
        await self._notify_log("Strateg", "Strateg agreguje výsledky všech agentů...")

        try:
            strategist_result = await strategist.execute(strategist_context)
        except Exception as e:
            await self._notify_log("Strateg", f"Chyba Strateg: {e}", "error")
            strategist_result = AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Strateg selhal: {e}",
                errors=[str(e)],
                details={"semaphore": "UNKNOWN", "semaphore_color": "gray"},
            )

        agent_results["Strateg"] = strategist_result

        for log_entry in strategist.logs:
            await self._notify_log("Strateg", log_entry.message, log_entry.level)

        await self._notify_status(
            "Strateg",
            strategist_result.status.value,
            {"elapsed_time": strategist.get_elapsed_time()},
        )

        self.results["Strateg"] = strategist.to_dict()
        gc.collect()

        total_time = round(time.time() - start_time, 2)
        self.is_running = False
        print(f"[Pipeline] COMPLETE in {total_time}s")

        final_result = {
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
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
            "is_running": self.is_running,
            "agents": {
                name: agent.to_dict()
                for name, agent in self.agents.items()
            },
        }
