"""Bounded Gemini intent suggestions for frozen image-edit requests.

Suggestions never alter image bindings, masks, geometry, or user-authored text.
"""
import base64
import io
import json
import re

import httpx
from PIL import Image

import config
import store

MAX_OPERATIONS = 20
MAX_TEXT = 220


def _image_data(aid):
    image = store.image(aid).convert('RGB')
    image.thumbnail((768, 768), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=82)
    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def _safe_text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= MAX_TEXT and not any(ord(c) < 32 for c in value)


def validate_suggestion(compiled, suggestion):
    """Allow explanatory constraints only for existing operation indices and inputs."""
    allowed = {b['display_index']: b for b in compiled.get('bindings', [])
               if b.get('kind') in ('element', 'main-edit') and isinstance(b.get('display_index'), int)}
    prompt = compiled.get('prompt', '')
    if not isinstance(suggestion, dict) or not isinstance(suggestion.get('operations'), list):
        return {'operations': []}
    accepted = []
    seen = set()
    for item in suggestion['operations'][:MAX_OPERATIONS]:
        if not isinstance(item, dict):
            continue
        index = item.get('display_index')
        if index not in allowed or index in seen:
            continue
        fields = ('intent', 'spatial', 'scale', 'identity')
        if any(not _safe_text(item.get(k)) for k in fields):
            continue
        confidence = item.get('confidence')
        if not isinstance(confidence, (int, float)) or not .7 <= confidence <= 1:
            continue
        uncertainty = item.get('uncertainty', '')
        if not isinstance(uncertainty, str) or uncertainty.strip().lower() not in ('', 'none', 'n/a', '无'):
            continue
        text = ' '.join(item[k] for k in fields)
        image_ids = {int(x) for x in re.findall(r'IMAGE\s+(\d+)', text, flags=re.I)}
        binding = allowed[index]
        permitted = {1, binding.get('input_index', 1)}
        # Other images may be described only when the user supplied an explicit role.
        permitted.update(b['input_index'] for b in compiled.get('bindings', [])
                         if b.get('kind') == 'full-image' and b.get('input_index')
                         and b.get('purpose', '').strip() not in ('', 'use as an overall visual reference'))
        if not image_ids <= permitted:
            continue
        # The calibration cannot negate the explicit location in the original prompt.
        original = prompt.lower()
        proposed = text.lower()
        if ('upper landing' in original or '上方平台' in original) and ('lower floor' in proposed or '下层' in proposed):
            continue
        if ('lower floor' in original or '下层地面' in original) and ('upper landing' in proposed or '上方平台' in proposed):
            continue
        seen.add(index)
        accepted.append({k: item[k].strip() for k in fields} | {'display_index': index, 'confidence': confidence})
    return {'operations': accepted}


def append_calibration(prompt, suggestion):
    operations = suggestion.get('operations', [])
    if not operations:
        return prompt
    lines = [prompt, 'Optional interpretation aids below; original user requirements, image bindings and locations always take precedence:']
    for item in operations:
        lines.append(f"Operation {item['display_index']} interpretation: intent={item['intent']}; "
                     f"spatial={item['spatial']}; scale={item['scale']}; identity={item['identity']}.")
    return '\n'.join(lines)


def suggest(compiled):
    """Call Gemini once for a read-only calibration proposal; no image generation."""
    if not config.GEMINI_KEY:
        raise RuntimeError('Gemini is not configured')
    prompt = (
        'You are an image-edit intent auditor, not an image generator. Read the frozen edit prompt and actual sent images. '
        'Return strict JSON {"operations":[{"display_index":1,"intent":"...","spatial":"...",'
        '"scale":"...","identity":"...","confidence":0.8,"uncertainty":"..."}]}. '
        'Only existing operation indices. Preserve original IMAGE numbering, locations, masks, names and user words. '
        'If target context makes placement or size uncertain, put that in uncertainty, use confidence below 0.7, '
        'and never invent a binding. For replacements, propose scale relative to the target object and adjacent scene; '
        'for people preserve body/head/hand proportions and feet/contact surface. '
        'Do not promise identical faces or exact pixel-level dimensions. '\
        '\nFROZEN PROMPT:\n' + compiled['prompt'][:15000]
    )
    content = [{'type': 'text', 'text': prompt}]
    for aid in compiled.get('inputs', [])[:13]:
        content.append({'type': 'image_url', 'image_url': {'url': _image_data(aid)}})
    payload = {'model': config.GEMINI_MODEL, 'messages': [{'role': 'user', 'content': content}],
               'temperature': 0, 'max_tokens': 1900, 'response_format': {'type': 'json_object'},
               'extra_body': {'generationConfig': {'thinkingConfig': {'thinkingBudget': 0}}}}
    with httpx.Client(timeout=httpx.Timeout(config.GEMINI_TIMEOUT, connect=10)) as client:
        response = client.post(config.GEMINI_BASE,
                               headers={'Authorization': 'Bearer ' + config.GEMINI_KEY}, json=payload)
    response.raise_for_status()
    body = response.json()
    text = body['choices'][0]['message']['content']
    if text.strip().startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    return {'suggestion': validate_suggestion(compiled, json.loads(text)), 'usage': body.get('usage', {})}
