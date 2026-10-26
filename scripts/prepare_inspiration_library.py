"""Prepare a categorized local library for import; never changes source files."""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def prepare(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups, skipped, seen = defaultdict(list), [], {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.avif'}:
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in {'_thumbnails', '待清理空文件', '非图片文件'}:
            continue
        try:
            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original).convert('RGBA' if 'A' in original.getbands() else 'RGB')
                image.load()
                digest = hashlib.sha256(str(image.size).encode() + image.convert('RGBA').tobytes()).hexdigest()
                if digest in seen:
                    skipped.append({'file': str(relative), 'reason': '重复图片', 'same_as': seen[digest]})
                    continue
                seen[digest] = str(relative)
                image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                filename = digest[:24] + '.png'
                image.save(output / filename)
            category = relative.parts[0] if len(relative.parts) > 1 else '其他'
            title = path.stem.replace('-', ' · ')
            if len(title) > 75 or re.match(r'^\d{10,}', path.stem):
                title = f'{category} · 素材 {len(groups[category]) + 1:02d}'
            description = f'{title}。来自你的本地图片分类库，归入「{category}」。可用于观察画面构图、主体摆放和色彩搭配，也可添加到工作区作为多图融合参考。'
            groups[category].append(dict(id='local-'+digest[:24], title=title, category=category,
                                        file=filename, source='本地图片分类库', description=description,
                                        tags=[category], original_file=str(relative)))
        except (UnidentifiedImageError, OSError, ValueError) as error:
            skipped.append({'file': str(relative), 'reason': str(error)})
    # Interleave categories so the first screen is not dominated by one folder.
    preferred=['美妆个护','服饰鞋包','食品饮料','数码3C','运动户外','珠宝腕表','家居生活']
    categories=preferred+[name for name in groups if name not in preferred]
    entries=[]
    for index in range(max(map(len, groups.values()), default=0)):
        for category in categories:
            if index < len(groups[category]):
                entries.append(groups[category][index])
    (output/'manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    report={'prepared':len(entries),'categories':{key:len(value) for key,value in groups.items()},'skipped':skipped}
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,args.output),ensure_ascii=False))
