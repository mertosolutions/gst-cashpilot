"""Gemini Live voice assistant. The browser streams microphone audio (PCM16, 16 kHz) over a WebSocket; this endpoint relays it to
Gemini Live and relays the spoken reply (PCM16, 24 kHz) and transcripts back. Questions about the user's data are answered by a tool
that runs the same exact, read-only search as the typed chat, so the assistant never invents numbers.

Frames to the server : binary = microphone audio | text JSON {"type":"text","text":"..."} | {"type":"end_audio"}
Frames to the browser: binary = reply audio | JSON {"type": ready | user_transcript | assistant_transcript | results | interrupted | turn_complete | error}"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import SessionLocal, set_tenant
from app.core.security import get_business, get_current_user
from app.services import analytics, gemini, voice_search

router = APIRouter(tags=["gemini live voice"])
logger = logging.getLogger(__name__)

INSTRUCTION = (
    "You are the voice assistant of GST CashPilot, a pre-filing GST tool for small business owners and CAs in India. "
    "Speak in the same language the user speaks (English, Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali or Gujarati). "
    "For ANY question about vendors, invoices, input tax credit (ITC), GSTR-2B mismatches or cash payable, call the function search_my_gst_data "
    "with the question written in English, then tell the user the answer in their language in one to three short sentences. "
    "Say amounts in rupees exactly as the function returns them. Never invent numbers, vendors or invoices. "
    "Never offer to file a return or give final tax advice: this is a draft tool and a CA reviews it. If the user only greets you, greet back briefly and say what you can do."
)


def _live_config():
    from google.genai import types
    s = get_settings()
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=INSTRUCTION,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=s.gemini_live_voice))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
            name="search_my_gst_data",
            description="Searches the user's saved GST results (vendors, invoices, ITC status, GSTR-2B matches, cash payable) and returns an exact answer.",
            parameters=types.Schema(type="OBJECT", properties={"question": types.Schema(type="STRING", description="The user's question, in English")}, required=["question"]))])],
    )


def _search(business_id: str, month: str, question: str) -> dict:
    with SessionLocal() as db:
        set_tenant(db, business_id)
        return voice_search.answer(db, business_id, question, month, "en-IN")


@router.websocket("/live")
async def live(ws: WebSocket, token: str | None = None, user: str | None = None, month: str | None = None):
    await ws.accept()
    s = get_settings()
    if token is None and user is None:
        try:
            auth = await asyncio.wait_for(ws.receive_json(), 10)
            if not isinstance(auth, dict) or auth.get("type") != "auth":
                raise ValueError("Expected authentication message")
            token = auth.get("token") if isinstance(auth.get("token"), str) else None
            user = auth.get("user") if isinstance(auth.get("user"), str) else None
        except (asyncio.TimeoutError, ValueError, json.JSONDecodeError):
            await ws.send_json({"type": "error", "message": "Voice sign-in was not received. Refresh the app and try again."})
            await ws.close(code=4401)
            return
        except WebSocketDisconnect:
            return
    def _identify() -> tuple[str, list[str]]:
        # blocking work (Firebase token check can call Google, first-time seeding writes the database): keep it off the event loop
        cu = get_current_user(authorization=f"Bearer {token}" if token else None, x_demo_user=user)
        with SessionLocal() as db:
            business = get_business(cu, db)
            return business.id, analytics.available_months(db, business.id)

    await ws.send_json({"type": "status", "text": "the API is checking your sign-in"})
    try:
        bid, months = await asyncio.wait_for(run_in_threadpool(_identify), 20)
    except asyncio.TimeoutError:
        await ws.send_json({"type": "error", "message": "Sign-in and data lookup timed out. Check the API logs and try again."})
        await ws.close(code=4408)
        return
    except HTTPException as exc:
        await ws.send_json({"type": "error", "message": str(exc.detail)})
        await ws.close(code=4401)
        return
    except Exception:
        logger.exception("Live session sign-in or data lookup failed")
        await ws.send_json({"type": "error", "message": "Sign-in or data lookup failed. Check the API logs and try again."})
        await ws.close(code=1011)
        return
    if not months:
        await ws.send_json({"type": "error", "message": "No data yet. Upload a purchase register and GSTR-2B first."})
        await ws.close(code=4404)
        return
    month = month if month in months else months[-1]
    if not get_settings().gemini_api_key:  # Gemini Live runs on the API key (not on Vertex), with its own model and quota, so the text chat's cooldown must not block it
        await ws.send_json({"type": "error", "message": "Gemini is not available right now (no key or the quota is used up). Type your question in the chat instead."})
        await ws.close(code=4503)
        return

    await ws.send_json({"type": "status", "text": "the API is connecting to Gemini Live"})
    from google.genai import types
    try:
        async with gemini._client(live=True).aio.live.connect(model=s.gemini_live_model, config=_live_config()) as session:  # noqa: E501
            await ws.send_json({"type": "ready", "model": s.gemini_live_model, "month": month})

            async def from_browser() -> None:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("bytes"):
                        await session.send_realtime_input(audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                    elif msg.get("text"):
                        data = json.loads(msg["text"])
                        if data.get("type") == "text" and data.get("text"):
                            await session.send_realtime_input(text=str(data["text"])[:500])
                        elif data.get("type") == "end_audio":
                            await session.send_realtime_input(audio_stream_end=True)

            async def from_gemini() -> None:
                while True:
                    async for m in session.receive():
                        if m.tool_call:
                            responses = []
                            for fc in m.tool_call.function_calls or []:
                                q = str((fc.args or {}).get("question") or "")
                                res = await run_in_threadpool(_search, bid, month, q)
                                await ws.send_json({"type": "results", "question": q, "data": res})
                                responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response={"answer": res["spoken"], "intent": res["intent"], "month": month}))
                            await session.send_tool_response(function_responses=responses)
                            continue
                        sc = m.server_content
                        if not sc:
                            continue
                        if sc.interrupted:
                            await ws.send_json({"type": "interrupted"})
                        if sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    await ws.send_bytes(part.inline_data.data)
                        if sc.input_transcription and sc.input_transcription.text:
                            await ws.send_json({"type": "user_transcript", "text": sc.input_transcription.text})
                        if sc.output_transcription and sc.output_transcription.text:
                            await ws.send_json({"type": "assistant_transcript", "text": sc.output_transcription.text})
                        if sc.turn_complete:
                            await ws.send_json({"type": "turn_complete"})

            tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_gemini())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - tell the browser, never leave it hanging
        quota = gemini.is_quota_error(exc)
        if quota:
            gemini.mark_quota_hit()
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "Gemini's quota is used up for now. Type your question instead." if quota else f"The voice session ended ({type(exc).__name__}). Try again."})
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
