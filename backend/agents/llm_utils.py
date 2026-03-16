"""Unified LLM client to support both Gemini and OpenAI providers."""
import json
import os
import base64
from typing import Optional, List, Any, Union
import httpx
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

class LLMClient:
    """Unified client for interacting with different LLM providers."""

    def __init__(self, model_name: str = "gemini"):
        self.model_name = model_name.lower()
        self.gemini_client = None
        
        if "gemini" in self.model_name:
            if GEMINI_API_KEY:
                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        elif "gpt" in self.model_name or "openai" in self.model_name:
            self.openai_api_key = OPENAI_API_KEY
            self.openai_base_url = OPENAI_BASE_URL
            self.openai_model = OPENAI_MODEL

    async def generate_content(
        self,
        system_instruction: str,
        contents: Union[str, List[Any]],
        response_mime_type: str = "text/plain",
        max_output_tokens: int = 2048,
        temperature: float = 0.7
    ) -> str:
        """Generate content from the selected LLM provider."""
        # Normalize contents to a list
        if isinstance(contents, str) or not isinstance(contents, list):
            contents = [contents]

        if "gemini" in self.model_name:
            return await self._generate_gemini(
                system_instruction, contents, response_mime_type, max_output_tokens, temperature
            )
        else:
            return await self._generate_openai_compatible(
                system_instruction, contents, response_mime_type, max_output_tokens, temperature
            )

    async def _generate_gemini(
        self,
        system_instruction: str,
        contents: List[Any],
        response_mime_type: str,
        max_output_tokens: int,
        temperature: float
    ) -> str:
        if not self.gemini_client:
            raise ValueError("Gemini client not initialized (check API key)")

        # In google-genai, contents can be a list of parts or strings
        # We assume the caller handles the specific Part/types formatting for now
        # but we can also normalize it here if needed.
        
        # Determine the model string to use
        # If model_name is just "gemini", use the default from config
        model = self.model_name if self.model_name != "gemini" else GEMINI_MODEL

        response = await self.gemini_client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type=response_mime_type,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
        )
        return response.text

    async def _generate_openai_compatible(
        self,
        system_instruction: str,
        contents: List[Any],
        response_mime_type: str,
        max_output_tokens: int,
        temperature: float
    ) -> str:
        """Call an OpenAI-compatible API gateway."""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not provided")

        messages = [{"role": "system", "content": system_instruction}]
        
        user_content = []
        for part in contents:
            if isinstance(part, str):
                user_content.append({"type": "text", "text": part})
            elif hasattr(part, "inline_data") and part.inline_data: # Gemini Part object from SDK
                encoded = base64.b64encode(part.inline_data.data).decode('utf-8')
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.inline_data.mime_type};base64,{encoded}"}
                })
            elif hasattr(part, "data") and hasattr(part, "mime_type"): # Fallback for other Part-like objects
                encoded = base64.b64encode(part.data).decode('utf-8')
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.mime_type};base64,{encoded}"}
                })
            else:
                # Fallback or generic handling
                user_content.append({"type": "text", "text": str(part)})
        
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self.openai_model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
        }
        
        if response_mime_type == "application/json":
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }

        # Handle SSL verification (often needed in corporate VPN environments)
        verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"

        async with httpx.AsyncClient(timeout=90.0, verify=verify_ssl) as client:
            url = f"{self.openai_base_url.rstrip('/')}/chat/completions"
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload
                )
                if response.status_code != 200:
                    print(f"OpenAI Gateway Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"LLMClient OpenAI error: {str(e)}")
                raise
