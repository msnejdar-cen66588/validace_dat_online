"""Pipeline Orchestrator – runs agents in parallel waves with real-time WebSocket updates."""
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


class PipelineOrchestrator:
    """Orchestrates the sequential execution of all validation agents."""

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
        self.agent_order = ["Strazce", "ForenzniAnalytik", "Historik", "Inspektor", "GeoValidator", "PorovnavacDokumentu", "KatastralniAnalytik", "Strateg"]
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

    async def run_pipeline(self, context: dict) -> dict:
        """Execute the full pipeline sequentially."""
        self.is_running = True
        start_time = time.time()

        await self.broadcast({
            "type": "pipeline_start",
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "timestamp": start_time,
            "agents": self.agent_order,
        })

        agent_results = {}

        # ── Execution Logic (Render free tier = 512MB RAM) ──
        import gc
        import asyncio

        async def _run_agent(agent_name: str):
            """Run a single agent."""
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
            return result

        # 1. Start with Strazce (fast fail)
        strazce_result = None
        try:
            strazce_result = await _run_agent("Strazce")
            agent_results["Strazce"] = strazce_result
        except Exception as e:
            await self._notify_log("Strazce", f"Agent selhal: {e}", "error")
            await self._notify_status("Strazce", "fail")
            self.results["Strazce"] = {
                "name": "Strazce", "status": "fail",
                "summary": f"Chyba: {e}", "errors": [str(e)],
            }
            strazce_result = AgentResult(status=AgentStatus.FAIL, summary=str(e), errors=[str(e)])
            agent_results["Strazce"] = strazce_result
        
        gc.collect()
        
        remaining_agents = []
        if strazce_result.status == AgentStatus.FAIL:
            await self._notify_log("Strateg", "Strazce vrátil FAIL. Přeskakuji rozsáhlejší agenty (šetřím paměť pre-Strategem).", "warn")
            
            skipped_agents = ["ForenzniAnalytik", "Historik", "Inspektor", "PorovnavacDokumentu", "KatastralniAnalytik", "GeoValidator"]
            for name in skipped_agents:
                agent_results[name] = AgentResult(status=AgentStatus.SUCCESS, summary="Přeskočeno (chyba fotodokumentace)")
                await self._notify_status(name, "success")
                self.results[name] = {"name": name, "status": "success", "summary": "Přeskočeno (chyba fotodokumentace)"}
        else:
            remaining_agents = ["ForenzniAnalytik", "Historik", "Inspektor", "PorovnavacDokumentu", "KatastralniAnalytik", "GeoValidator"]

        # 2. Run remaining concurrently with a semaphore of 2 to protect RAM
        sem = asyncio.Semaphore(2)

        async def _run_agent_with_sem(agent_name: str):
            async with sem:
                try:
                    res = await _run_agent(agent_name)
                    gc.collect()
                    return agent_name, res
                except Exception as e:
                    await self._notify_log(agent_name, f"Agent selhal: {e}", "error")
                    await self._notify_status(agent_name, "fail")
                    self.results[agent_name] = {
                        "name": agent_name, "status": "fail",
                        "summary": f"Chyba: {e}", "errors": [str(e)],
                    }
                    return agent_name, AgentResult(status=AgentStatus.FAIL, summary=str(e), errors=[str(e)])

        if remaining_agents:
            tasks = [_run_agent_with_sem(name) for name in remaining_agents]
            gathered = await asyncio.gather(*tasks)
            for name, res in gathered:
                agent_results[name] = res

        # Run Strateg with all previous results
        strategist = self.agents["Strateg"]
        strategist_context = {**context, "agent_results": agent_results}

        if context.get("custom_prompts", {}).get("Strateg"):
            strategist.system_prompt = context["custom_prompts"]["Strateg"]

        await self._notify_status("Strateg", "processing")
        await self._notify_log("Strateg", "Strateg aggregating all results...")

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

        total_time = round(time.time() - start_time, 2)
        self.is_running = False

        # Final pipeline result
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
