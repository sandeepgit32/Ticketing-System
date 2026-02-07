import os
import uuid
import time
import hmac
import hashlib
import json
from fastapi import FastAPI, Header, HTTPException
from fastapi.background import BackgroundTasks
import httpx

app = FastAPI(title='Mock Payment Provider')
intents = {}
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'secret')
BOOKING_WEBHOOK_URL = os.getenv('BOOKING_WEBHOOK_URL', 'http://booking:8000/payments/webhook')


@app.post('/payments/intents')
async def create_intent(payload: dict, idempotency_key: str = Header(None)):
    # idempotency supported via header
    if idempotency_key and idempotency_key in intents:
        return intents[idempotency_key]
    intent_id = str(uuid.uuid4())
    intent = {'intent_id': intent_id, 'status': 'requires_confirmation', 'payload': payload}
    if idempotency_key:
        intents[idempotency_key] = intent
    return intent


@app.post('/payments/intents/{intent_id}/confirm')
async def confirm_intent(intent_id: str, background: BackgroundTasks, delay_ms: int = 0, success: bool = True):
    # find intent
    # schedule webhook
    payload = {'event': 'capture_succeeded' if success else 'capture_failed', 'payment_id': str(uuid.uuid4()), 'intent_id': intent_id, 'timestamp': int(time.time())}

    async def send_webhook():
        await httpx.AsyncClient().post(BOOKING_WEBHOOK_URL, json=payload, headers={'X-Signature': generate_signature(json.dumps(payload))})

    background.add_task(send_webhook)
    return {'ok': True, 'scheduled': True}


def generate_signature(body: str) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


@app.post('/admin/next')
async def set_next(payload: dict):
    # placeholder for deterministic behavior
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=9000)
