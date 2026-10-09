"""Bounded, explicitly authorized paid Image2.5 experiments. Resume never repeats a sent call.
Public photographs and hand-authored polygons are research fixtures, not AI mask claims.
"""
import argparse
import copy
import json
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config
import store
import provider

OUT = ROOT / 'evidence' / 'real'; OUT.mkdir(parents=True, exist_ok=True)


def fixture():
    saved = OUT / 'fixtures.json'
    if saved.exists():
        return json.loads(saved.read_text(encoding='utf-8'))
    assets = {name: store.ingest((ROOT / 'evidence/samples' / (name + '.png')).read_bytes(), name)
              for name in ['fashion-a', 'fashion-b', 'bag', 'shoes']}
    # Coordinates are normalized from inspected photographs. These are explicit manual selections.
    shapes = {
        'bag-source': ('bag', [[.2,.26],[.72,.15],[.83,.66],[.74,.8],[.19,.84],[.14,.64]], [.5,.5]),
        'shoe-source': ('shoes', [[.19,.78],[.23,.65],[.39,.43],[.49,.16],[.63,.21],[.69,.015],[.78,.02],[.83,.32],[.64,.73],[.4,.88],[.21,.89]], [.53,.5]),
        'glasses-source': ('fashion-b', [[.51,.32],[.64,.30],[.64,.36],[.55,.38]], [.58,.34]),
        'glasses-a-source': ('fashion-a', [[.42,.216],[.51,.219],[.516,.232],[.445,.24]], [.465,.229]),
        'bag-a': ('fashion-a', [[.34,.433],[.49,.426],[.515,.47],[.477,.53],[.352,.536],[.323,.507]], [.41,.48]),
        'shoes-a': ('fashion-a', [[.372,.798],[.445,.798],[.482,.885],[.445,.94],[.399,.941],[.393,.87],[.637,.804],[.701,.802],[.753,.899],[.743,.952],[.679,.96],[.651,.91]], [.43,.89]),
        'glasses-a': ('fashion-a', [[.42,.216],[.51,.219],[.516,.232],[.445,.24]], [.465,.229]),
        'left-bag-b': ('fashion-b', [[.08,.59],[.30,.48],[.39,.69],[.40,.948],[.17,.90]], [.28,.78]),
        'right-bag-b': ('fashion-b', [[.79,.63],[.949,.60],[.997,.779],[.998,.992],[.793,.997],[.718,.86]], [.9,.85]),
        'glasses-b': ('fashion-b', [[.51,.32],[.64,.30],[.64,.36],[.55,.38]], [.58,.34]),
        'coat-source': ('fashion-b', [[.45,.41],[.525,.404],[.68,.401],[.712,.565],[.743,.69],[.804,.612],[.841,.651],[.806,.771],[.745,.862],[.697,.77],[.715,.998],[.594,.998],[.615,.79],[.617,.56],[.565,.46],[.481,.553],[.449,.997],[.391,.997],[.41,.688],[.388,.793],[.344,.824],[.31,.709],[.328,.551],[.376,.554],[.388,.69],[.421,.528]], [.45,.63]),
        'coat-a': ('fashion-a', [[.325,.285],[.378,.279],[.402,.328],[.473,.319],[.56,.30],[.716,.34],[.756,.306],[.814,.338],[.793,.389],[.704,.406],[.582,.362],[.599,.55],[.65,.724],[.556,.76],[.491,.744],[.46,.576],[.471,.538],[.521,.483],[.50,.427],[.367,.44],[.315,.421],[.243,.376],[.229,.349]], [.35,.373]),
    }
    masks = {}
    for name, (photo, polygon, anchor) in shapes.items():
        mask = store.manual_mask(assets[photo]['id'], polygon)
        masks[name] = {'image_id': assets[photo]['id'], 'image_version': 1, 'mask_id': mask['id'], 'anchor': {'x': anchor[0], 'y': anchor[1]}}
    def state(name, base, pairs):
        d = store.new_draft(); d['name'] = name; d['main_image'] = assets[base]['id']; d['mappings'] = []
        for i, (source, target, label) in enumerate(pairs):
            src = copy.deepcopy(masks[source]); src['label'] = label; src['label_source'] = 'user'
            d['mappings'].append({'id': store.uid(), 'display_index': i+1, 'color': store.COLORS[i], 'mode': 'replace', 'source': src, 'target': masks[target]})
        d['references'] = list(dict.fromkeys(m['source']['image_id'] for m in d['mappings']))
        d['next_display_index'] = len(pairs)+1
        return d
    bag=('bag-source','bag-a','黑色绗缝金链包'); shoe=('shoe-source','shoes-a','红色运动鞋'); glasses=('glasses-source','glasses-a','黑色太阳镜')
    fixtures = {
        '01-single-bag': state('01 单对象 · 包', 'fashion-a', [bag]),
        '02-single-shoes': state('02 单对象 · 鞋', 'fashion-a', [shoe]),
        '03-single-glasses': state('03 单对象 · 眼镜', 'fashion-a', [glasses]),
        '04-two-bag-shoes': state('04 两对象 · 包和鞋', 'fashion-a', [bag,shoe]),
        '05-two-bag-glasses': state('05 两对象 · 包和眼镜', 'fashion-a', [bag,glasses]),
        '06-two-shoes-glasses': state('06 两对象 · 鞋和眼镜', 'fashion-a', [shoe,glasses]),
        '07-three-a': state('07 三对象 · 包鞋眼镜', 'fashion-a', [bag,shoe,glasses]),
        '08-three-b': state('08 三对象 · 双手提包和眼镜', 'fashion-b', [('bag-source','left-bag-b','黑色绗缝金链包'),('bag-source','right-bag-b','黑色绗缝金链包'),('glasses-a-source','glasses-b','猫眼太阳镜')]),
        '09-occluded-coat': state('09 难例 · 围巾鸽子遮挡的大衣', 'fashion-a', [('coat-source','coat-a','酒红大衣')]),
        '10-held-bag': state('10 难例 · 手套与提包遮挡', 'fashion-b', [('bag-source','left-bag-b','黑色绗缝金链包')]),
    }
    # Hand drawn masks are verified by the same app validator before any call.
    for name, st in fixtures.items():
        store.validate(st, True)
    saved.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding='utf-8')
    return fixtures


def run_one(name, state, strategy='full', mask_kind=None):
    destination = OUT / (name + '.json')
    if destination.exists():
        return json.loads(destination.read_text(encoding='utf-8'))
    compiled = provider.compile_request(state, strategy)
    compiled['size'] = 'auto'
    native_mask = None
    if mask_kind:
        im = store.image(state['main_image'])
        values = np.zeros((im.height, im.width), dtype=np.uint8)
        for mapping in state['mappings']:
            values = np.maximum(values, np.asarray(store.image(mapping['target']['mask_id']).getchannel('A')))
        mask = Image.fromarray(values)
        if mask_kind in ('dilate', 'feather'):
            mask = mask.filter(ImageFilter.MaxFilter(13)) # radius 6 at input resolution
        if mask_kind == 'feather':
            mask = mask.filter(ImageFilter.GaussianBlur(4))
        # Experimental OpenAI-style alpha hypothesis: transparent pixels mark edit area.
        rgba = Image.new('RGBA', mask.size, (0,0,0,255)); rgba.putalpha(Image.fromarray(255-np.asarray(mask)))
        native_mask = provider.png(rgba)
        (OUT / (name+'-request-mask.png')).write_bytes(native_mask)
        compiled['mask_mode'] = 'experimental-' + mask_kind
        compiled['mask_parameters'] = {'dilation_radius_px': 6 if mask_kind != 'hard' else 0,
            'feather_radius_px': 4 if mask_kind == 'feather' else 0,
            'alpha_hypothesis': 'transparent means edit; not proven',
            'request_file': name+'-request-mask.png'}
    record = {'name': name, 'state': state, 'compiled': compiled, 'mask_experiment': mask_kind,
              'started_at': time.time(), 'status': 'sent', 'calls': 1}
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('CALL', name, flush=True)
    start = time.monotonic()
    try:
        result = provider.call(compiled, native_mask)
        record.update(status='saving', result=result)
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        jid = store.uid()
        snapshot = {'state': state, 'compiled': compiled, 'mode': 'live', 'model': config.MODEL, 'research_case': name}
        with store.db() as con:
            con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',
                        (jid, 'research-'+name, time.time(), 'saving', json.dumps(snapshot), json.dumps(result)))
        provider.save_outputs(jid)
        job = store.job(jid)
        record.update(status=job['status'], result=job['result'], history_id=jid)
        for i, aid in enumerate(job['result'].get('assets', [])):
            (OUT / f'{name}-output-{i}.png').write_bytes((config.DATA/store.asset(aid)['path']).read_bytes())
    except Exception as exc:
        record.update(status='failed-or-unknown', error=str(exc)[:700])
    record['wall_s'] = round(time.monotonic()-start, 3)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE', name, record['status'], record['wall_s'], flush=True)
    return record


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--phase', choices=['minimal','compare','serial-second','quality','mask'], default='minimal'); args=parser.parse_args()
    store.init(); provider.preflight(); fixtures=fixture()
    if args.phase=='minimal':
        run_one('01-single-bag', fixtures['01-single-bag'])
    elif args.phase=='compare':
        original=fixtures['04-two-bag-shoes']
        for strategy in ['full','context-crop','transparent']:
            run_one('compare-batch-'+strategy, original, strategy)
        first=copy.deepcopy(original); first['mappings']=first['mappings'][:1]
        r=run_one('compare-serial-1',first)
        print('Inspect serial step 1 alignment before running --phase serial-second', flush=True)
    elif args.phase=='serial-second':
        original=fixtures['04-two-bag-shoes']
        r=json.loads((OUT/'compare-serial-1.json').read_text(encoding='utf-8'))
        # Operator invokes this phase only after inspecting step 1 for target-region drift.
        if r.get('result',{}).get('assets'):
            second=copy.deepcopy(original); second['mappings']=second['mappings'][1:]; second['main_image']=r['result']['assets'][0]
            src=store.image(original['main_image']); out=store.image(second['main_image'])
            record={'original_size':src.size,'intermediate_size':out.size,'note':'Research-only normalized coordinates; inspect alignment visually before claiming serial safe.'}
            (OUT/'serial-drift.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            if src.size != out.size:
                raise ValueError('Reconfirm target geometry after intermediate image resize')
            for mapping in second['mappings']:
                target = mapping['target']
                target['mask_id'] = store.mask_asset(store.image(target['mask_id']).getchannel('A'),
                    second['main_image'], 'research-version-binding')['id']
                target['image_id'] = second['main_image']
            store.validate(second, True)
            run_one('compare-serial-2',second)
    elif args.phase=='quality':
        for name,st in fixtures.items():
            run_one(name,st,'context-crop')
    elif args.phase=='mask':
        for kind in ['hard','dilate','feather']:
            run_one('mask-'+kind,fixtures['01-single-bag'],'context-crop',kind)
