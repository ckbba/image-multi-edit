"""Standalone RapidOCR process to isolate native ONNX/OpenCV libraries."""
import json
import sys

from PIL import Image
from rapidocr import RapidOCR


def main(path):
    width, height = Image.open(path).size
    result = RapidOCR()(path)
    rows = getattr(result, 'txts', None)
    scores = getattr(result, 'scores', None)
    boxes = getattr(result, 'boxes', None)
    if rows is None and isinstance(result, (list, tuple)):
        rows = [item[1] for item in (result[0] or [])]
        scores = [item[2] for item in (result[0] or [])]
        boxes = [item[0] for item in (result[0] or [])]
    rows = [] if rows is None else rows
    scores = [] if scores is None else scores
    boxes = [] if boxes is None else boxes
    items = []
    for text, score, points in zip(rows, scores, boxes):
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        bbox = [max(0, min(xs) / width), max(0, min(ys) / height), min(1, max(xs) / width), min(1, max(ys) / height)]
        polygon = [[round(max(0, min(1, float(p[0]) / width)), 6), round(max(0, min(1, float(p[1]) / height)), 6)] for p in points]
        items.append({'text': str(text), 'confidence': round(float(score), 4), 'bbox': [round(v, 6) for v in bbox], 'polygon': polygon})
    print(json.dumps({'items': items}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])